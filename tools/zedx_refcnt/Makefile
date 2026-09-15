KDIR ?= /lib/modules/$(shell uname -r)/build
obj-m := zedx_refcnt.o

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
