"""
Point Cloud & Grid Map 데이터 로더
지원 포맷: PCD, CSV/TXT, LAS/LAZ, NPY/NPZ
"""
import numpy as np
from pathlib import Path


def load_point_cloud(filepath: str) -> np.ndarray:
    """
    포인트 클라우드 파일 로드. 결과는 (N, 3) numpy array (x, y, z).
    지원: .pcd, .csv, .txt, .las, .laz, .npy, .npz, .ply
    """
    path = Path(filepath)
    suffix = path.suffix.lower()

    loaders = {
        '.pcd': _load_pcd,
        '.csv': _load_csv,
        '.txt': _load_csv,
        '.las': _load_las,
        '.laz': _load_las,
        '.npy': _load_npy,
        '.npz': _load_npz,
        '.ply': _load_ply,
    }

    loader = loaders.get(suffix)
    if loader is None:
        raise ValueError(f"지원하지 않는 파일 형식: {suffix}")

    points = loader(str(path))

    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError(f"포인트 클라우드는 (N, 3) 이상이어야 합니다. 현재: {points.shape}")

    return points[:, :3].astype(np.float64)


def _load_pcd(filepath: str) -> np.ndarray:
    """PCD 파일 로드 (open3d 사용)"""
    try:
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(filepath)
        return np.asarray(pcd.points)
    except ImportError:
        return _load_pcd_manual(filepath)


def _load_pcd_manual(filepath: str) -> np.ndarray:
    """PCD 파일 수동 파싱 (ASCII 형식만)"""
    points = []
    data_started = False
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('DATA'):
                fmt = line.split()[-1]
                if fmt != 'ascii':
                    raise ValueError("open3d 없이는 ASCII PCD만 지원합니다")
                data_started = True
                continue
            if data_started and line:
                vals = line.split()
                if len(vals) >= 3:
                    points.append([float(vals[0]), float(vals[1]), float(vals[2])])
    return np.array(points)


def _load_csv(filepath: str) -> np.ndarray:
    """CSV/TXT 파일 로드"""
    for delimiter in [',', ' ', '\t', ';']:
        try:
            data = np.loadtxt(filepath, delimiter=delimiter, comments='#', skiprows=0)
            if data.ndim == 2 and data.shape[1] >= 3:
                return data
        except (ValueError, IndexError):
            pass

    # 첫 줄이 헤더일 수 있음
    for delimiter in [',', ' ', '\t', ';']:
        try:
            data = np.loadtxt(filepath, delimiter=delimiter, comments='#', skiprows=1)
            if data.ndim == 2 and data.shape[1] >= 3:
                return data
        except (ValueError, IndexError):
            pass

    raise ValueError(f"CSV/TXT 파일을 파싱할 수 없습니다: {filepath}")


def _load_las(filepath: str) -> np.ndarray:
    """LAS/LAZ 파일 로드"""
    import laspy
    las = laspy.read(filepath)
    return np.column_stack([las.x, las.y, las.z])


def _load_npy(filepath: str) -> np.ndarray:
    """NumPy .npy 파일 로드"""
    return np.load(filepath)


def _load_npz(filepath: str) -> np.ndarray:
    """NumPy .npz 파일 로드 (첫 번째 배열 사용)"""
    data = np.load(filepath)
    key = list(data.keys())[0]
    return data[key]


def _load_ply(filepath: str) -> np.ndarray:
    """PLY 파일 로드"""
    try:
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(filepath)
        return np.asarray(pcd.points)
    except ImportError:
        raise ImportError("PLY 파일 로드에는 open3d가 필요합니다")


def load_grid_map(filepath: str) -> dict:
    """
    2D Grid Map 로드.
    반환: {
        'grid': 2D numpy array (높이값),
        'resolution': float (m/cell),
        'origin': (x, y) 좌표
    }
    """
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == '.npy':
        grid = np.load(filepath)
    elif suffix == '.npz':
        data = np.load(filepath)
        if 'grid' in data:
            grid = data['grid']
            resolution = float(data.get('resolution', 0.05))
            origin = tuple(data.get('origin', (0.0, 0.0)))
            return {'grid': grid, 'resolution': resolution, 'origin': origin}
        grid = data[list(data.keys())[0]]
    elif suffix in ['.csv', '.txt']:
        for delimiter in [',', ' ', '\t']:
            try:
                grid = np.loadtxt(filepath, delimiter=delimiter)
                if grid.ndim == 2:
                    break
            except (ValueError, IndexError):
                pass
        else:
            raise ValueError(f"Grid map 파일을 파싱할 수 없습니다: {filepath}")
    else:
        raise ValueError(f"지원하지 않는 Grid map 형식: {suffix}")

    return {'grid': grid, 'resolution': 0.05, 'origin': (0.0, 0.0)}


def save_point_cloud(points: np.ndarray, filepath: str):
    """포인트 클라우드 저장"""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == '.pcd':
        try:
            import open3d as o3d
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(points[:, :3])
            o3d.io.write_point_cloud(filepath, pcd)
        except ImportError:
            _save_pcd_ascii(points, filepath)
    elif suffix in ['.csv', '.txt']:
        np.savetxt(filepath, points, delimiter=',', header='x,y,z', comments='')
    elif suffix == '.npy':
        np.save(filepath, points)
    elif suffix == '.ply':
        import open3d as o3d
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points[:, :3])
        o3d.io.write_point_cloud(filepath, pcd)
    else:
        raise ValueError(f"지원하지 않는 저장 형식: {suffix}")


def _save_pcd_ascii(points: np.ndarray, filepath: str):
    """PCD ASCII 형식으로 저장"""
    n = len(points)
    with open(filepath, 'w') as f:
        f.write("# .PCD v0.7 - Point Cloud Data file format\n")
        f.write("VERSION 0.7\n")
        f.write("FIELDS x y z\n")
        f.write("SIZE 4 4 4\n")
        f.write("TYPE F F F\n")
        f.write("COUNT 1 1 1\n")
        f.write(f"WIDTH {n}\n")
        f.write("HEIGHT 1\n")
        f.write("VIEWPOINT 0 0 0 1 0 0 0\n")
        f.write(f"POINTS {n}\n")
        f.write("DATA ascii\n")
        for p in points:
            f.write(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")


def save_grid_map(grid_data: dict, filepath: str):
    """Grid map 저장"""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if suffix == '.npz':
        np.savez(filepath,
                 grid=grid_data['grid'],
                 resolution=grid_data.get('resolution', 0.05),
                 origin=grid_data.get('origin', (0.0, 0.0)))
    elif suffix == '.npy':
        np.save(filepath, grid_data['grid'])
    elif suffix in ['.csv', '.txt']:
        np.savetxt(filepath, grid_data['grid'], delimiter=',')
    else:
        raise ValueError(f"지원하지 않는 저장 형식: {suffix}")
