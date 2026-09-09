// SPDX-License-Identifier: GPL-2.0
/*
 * zedx_refcnt - inspect and repair the module reference count of a Tegra camera
 * sensor driver after the tegracam stream-stop path has leaked a module_put().
 *
 * Why this exists
 * ---------------
 * NVIDIA's tegracam V4L2 glue takes a module reference when streaming starts and
 * releases it when streaming stops. When the sensor's stop_streaming() returns an
 * error the stop path still falls through to the error label and calls
 * module_put() a second time, so one reference is released twice:
 *
 *   zedx 10-0020: Error turning off streaming
 *   WARNING at kernel/module.c:1095 module_put+0x18c
 *     module_put <- tegracam_v4l2subdev_register <- tegra_channel_set_stream
 *                <- _vb2_fop_release <- __fput <- do_exit
 *
 * module_put() floors the counter at 0 (atomic_dec_if_positive), so the damage
 * stops at atomic refcnt 0 - which is one BELOW the base reference every module
 * gets at load time. /sys/module/<m>/refcnt then reads -1, rmmod can never
 * succeed, and the vendor recovery (systemctl restart zed_x_daemon, which is
 * rmmod + insmod) silently no-ops while still logging "ZED-X Driver loaded".
 *
 * Restoring exactly that one base reference makes the module removable again, so
 * the documented driver-reload recovery works without rebooting.
 *
 * Safety
 * ------
 * - Reaches the target through driver_find(<i2c driver>, &i2c_bus_type)->owner,
 *   so there is no module-list walking and no unexported symbol.
 * - Refuses unless the owner module's name equals `target`, so a wrong driver
 *   name can never touch the wrong module.
 * - Only ever uses exported, BUG-free helpers: __module_get() / try_module_get()
 *   (plain atomic_inc, no BUG_ON) and module_put() (WARN_ON only). Never writes
 *   mod->refcnt directly.
 * - delta<0 stops at the base reference, so this tool cannot create the damage
 *   it repairs. Reproducing the damaged state for testing needs unsafe_break=1.
 *
 * HAZARD: on a kernel with panic_on_oops=1, running rmmod while the atomic
 * refcount is 0 can hit BUG_ON(ret < 0) in try_release_module_ref() and panic the
 * machine. Always repair first, confirm /sys/module/<m>/refcnt >= 0, then rmmod.
 *
 * Params:
 *   target=<module>   module name that must own the driver   (default sl_zedx)
 *   driver=<name>     i2c driver to look up                  (default zedx)
 *   delta=<n>         add n references (>0) / release -n (<0), floored at base
 *   repair=1          restore the base reference if it was lost
 *   unsafe_break=1    TEST ONLY: drop the base reference of an idle module
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/device.h>
#include <linux/i2c.h>
#include <linux/string.h>

/* Value the kernel stores in mod->refcnt at load time; sysfs shows refcnt - this. */
#define ZEDX_MODULE_REF_BASE 1

static char *target = "sl_zedx";
module_param(target, charp, 0444);
MODULE_PARM_DESC(target, "module name that must own the driver");

static char *driver = "zedx";
module_param(driver, charp, 0444);
MODULE_PARM_DESC(driver, "i2c driver name to look up");

static int delta;
module_param(delta, int, 0444);
MODULE_PARM_DESC(delta, "add (>0) or release (<0) references; never below base");

static bool repair;
module_param(repair, bool, 0444);
MODULE_PARM_DESC(repair, "restore the base reference if it was lost");

static bool unsafe_break;
module_param(unsafe_break, bool, 0444);
MODULE_PARM_DESC(unsafe_break, "TEST ONLY: drop the base reference of an idle module");

static int __init zedx_refcnt_init(void)
{
	struct device_driver *drv;
	struct module *mod;
	int before, after, i;
	const char *action = "report";

	drv = driver_find(driver, &i2c_bus_type);
	if (!drv) {
		pr_err("zedx_refcnt: no i2c driver named '%s'\n", driver);
		return -ENODEV;
	}
	mod = drv->owner;
	if (!mod) {
		pr_err("zedx_refcnt: driver '%s' has no owning module\n", driver);
		return -ENODEV;
	}
	if (strcmp(mod->name, target) != 0) {
		pr_err("zedx_refcnt: refusing: driver '%s' is owned by '%s', not '%s'\n",
		       driver, mod->name, target);
		return -ENODEV;
	}
	if (!module_is_live(mod)) {
		pr_err("zedx_refcnt: refusing: '%s' is not live (state=%d)\n",
		       mod->name, mod->state);
		return -ENODEV;
	}

	before = atomic_read(&mod->refcnt);
	pr_info("zedx_refcnt: target=%s driver=%s atomic_refcnt=%d sysfs_refcnt=%d state=%d\n",
		mod->name, driver, before, before - ZEDX_MODULE_REF_BASE, mod->state);

	if (repair) {
		action = "repair";
		if (before >= ZEDX_MODULE_REF_BASE) {
			pr_info("zedx_refcnt: %s is undamaged (atomic %d >= base %d), nothing to do\n",
				mod->name, before, ZEDX_MODULE_REF_BASE);
		} else {
			while (atomic_read(&mod->refcnt) < ZEDX_MODULE_REF_BASE)
				__module_get(mod);
			pr_warn("zedx_refcnt: restored the base reference of %s: %d -> %d\n",
				mod->name, before, atomic_read(&mod->refcnt));
		}
	} else if (unsafe_break) {
		action = "unsafe_break";
		if (before != ZEDX_MODULE_REF_BASE) {
			pr_err("zedx_refcnt: refusing to break %s: atomic %d != base %d (module in use or already broken)\n",
			       mod->name, before, ZEDX_MODULE_REF_BASE);
			return -EBUSY;
		}
		pr_warn("zedx_refcnt: UNSAFE: dropping the base reference of %s to reproduce the wedge\n",
			mod->name);
		module_put(mod);
	} else if (delta > 0) {
		action = "get";
		for (i = 0; i < delta; i++) {
			if (!try_module_get(mod)) {
				pr_err("zedx_refcnt: try_module_get failed at %d/%d (atomic=%d); rolling back\n",
				       i, delta, atomic_read(&mod->refcnt));
				while (i-- > 0)
					module_put(mod);
				return -EAGAIN;
			}
		}
	} else if (delta < 0) {
		action = "put";
		for (i = 0; i < -delta; i++) {
			if (atomic_read(&mod->refcnt) <= ZEDX_MODULE_REF_BASE) {
				pr_warn("zedx_refcnt: stopping at the base reference (atomic=%d) after %d of %d puts\n",
					atomic_read(&mod->refcnt), i, -delta);
				break;
			}
			module_put(mod);
		}
	}

	after = atomic_read(&mod->refcnt);
	pr_info("zedx_refcnt: done action=%s atomic_before=%d atomic_after=%d sysfs_after=%d\n",
		action, before, after, after - ZEDX_MODULE_REF_BASE);
	return 0;
}

static void __exit zedx_refcnt_exit(void)
{
	pr_info("zedx_refcnt: unloaded\n");
}

module_init(zedx_refcnt_init);
module_exit(zedx_refcnt_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Inspect/repair a tegracam sensor module reference count");
