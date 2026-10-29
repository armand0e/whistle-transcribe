"""NVIDIA CUDA detection and DLL search paths, confined to inference children."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys

_dll_handles = []

def configure_cuda():
    roots = [Path(sys.prefix) / 'Lib' / 'site-packages', Path(sys.base_prefix) / 'Lib' / 'site-packages']
    directories = []
    for root in roots:
        directories.extend([root / 'torch' / 'lib', root / 'nvidia' / 'cublas' / 'bin', root / 'nvidia' / 'cudnn' / 'bin', root / 'nvidia' / 'cuda_runtime' / 'bin'])
    toolkit = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'NVIDIA GPU Computing Toolkit' / 'CUDA'
    for version in sorted(toolkit.glob('v*'), reverse=True):
        directories.extend([version / 'bin', version / 'bin' / 'x64'])
    if os.environ.get('CUDA_PATH'):
        directories.append(Path(os.environ['CUDA_PATH']) / 'bin')
    directories = list(dict.fromkeys(path for path in directories if path.is_dir()))
    os.environ['PATH'] = os.pathsep.join(map(str, directories)) + os.pathsep + os.environ.get('PATH', '')
    for directory in directories:
        _dll_handles.append(os.add_dll_directory(str(directory)))
    for name in ('cublas64_12.dll', 'cublasLt64_12.dll', 'cudnn64_9.dll'):
        try:
            _dll_handles.append(ctypes.WinDLL(name))
        except OSError as exc:
            raise RuntimeError(f'NVIDIA CUDA needs {name}. Install CUDA 12 and cuDNN 9, or select CPU. ({exc})') from exc

def gpu_info():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'NVIDIA driver did not respond.')
        name, total, free = result.stdout.splitlines()[0].rsplit(',', 2)
        return {'name': name.strip(), 'total_mb': int(total), 'free_mb': int(free), 'index': 0}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('No usable NVIDIA GPU/driver was detected. Select CPU.') from exc

def cuda_probe():
    information = gpu_info()
    configure_cuda()
    import ctranslate2
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError('The NVIDIA CUDA runtime could not find a GPU. Select CPU.')
    supported = ctranslate2.get_supported_compute_types('cuda', 0)
    information['compute_type'] = 'float16' if 'float16' in supported else 'float32'
    return information
