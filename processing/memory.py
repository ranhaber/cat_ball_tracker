"""
Memory management utilities for Cat Dome.

Provides:
- get_system_info(): RAM, CPU, temperature readings from /proc
- get_ram_stats(): Compact RAM stats string for debug logging
- reclaim_memory(): Force OS to reclaim freed heap pages (gc + malloc_trim)

These functions are safe to call from any thread and never affect
active allocations — they only accelerate release of already-freed memory.
"""

import os
import gc


def get_system_info():
    """Get RAM usage, CPU usage, and CPU temperature for Raspberry Pi.
    
    Reads from /proc/meminfo, /proc/stat, and thermal zone.
    Returns dict with keys: ram_used_mb, ram_total_mb, ram_percent,
    cpu_percent, cpu_temp. Values are None if unavailable.
    """
    info = {
        "ram_used_mb": None,
        "ram_total_mb": None,
        "ram_percent": None,
        "cpu_percent": None,
        "cpu_temp": None
    }
    
    try:
        # Get memory info from /proc/meminfo
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = int(parts[1])  # Value in kB
                    meminfo[key] = value
            
            total_kb = meminfo.get('MemTotal', 0)
            available_kb = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
            used_kb = total_kb - available_kb
            
            info["ram_total_mb"] = round(total_kb / 1024)
            info["ram_used_mb"] = round(used_kb / 1024)
            if total_kb > 0:
                info["ram_percent"] = round((used_kb / total_kb) * 100, 1)
    except Exception:
        pass
    
    try:
        # Get CPU usage from /proc/stat (average across all cores)
        with open('/proc/stat', 'r') as f:
            line = f.readline()  # First line is total CPU
            if line.startswith('cpu '):
                parts = line.split()
                # user, nice, system, idle, iowait, irq, softirq
                if len(parts) >= 5:
                    idle = int(parts[4])
                    total = sum(int(x) for x in parts[1:8] if x.isdigit())
                    
                    # Store for delta calculation
                    if not hasattr(get_system_info, '_last_cpu'):
                        get_system_info._last_cpu = (idle, total)
                        info["cpu_percent"] = 0
                    else:
                        last_idle, last_total = get_system_info._last_cpu
                        idle_delta = idle - last_idle
                        total_delta = total - last_total
                        
                        if total_delta > 0:
                            cpu_used = 100.0 * (1.0 - idle_delta / total_delta)
                            info["cpu_percent"] = round(cpu_used, 1)
                        
                        get_system_info._last_cpu = (idle, total)
    except Exception:
        pass
    
    try:
        # Get CPU temperature from Raspberry Pi thermal zone
        temp_path = '/sys/class/thermal/thermal_zone0/temp'
        if os.path.exists(temp_path):
            with open(temp_path, 'r') as f:
                temp_millicelsius = int(f.read().strip())
                info["cpu_temp"] = round(temp_millicelsius / 1000, 1)
    except Exception:
        pass
    
    return info


def get_ram_stats():
    """Get compact RAM stats string for debug logging.
    
    Returns string like:
        'avail=138MB/416MB, proc_rss=124MB, proc_swap=49MB, sys_swap=110MB'
    Returns 'N/A' on error.
    """
    try:
        # System RAM
        mem = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                if parts[0].rstrip(':') in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
                    mem[parts[0].rstrip(':')] = int(parts[1])
        avail_mb = mem.get('MemAvailable', 0) // 1024
        total_mb = mem.get('MemTotal', 0) // 1024
        swap_used_mb = (mem.get('SwapTotal', 0) - mem.get('SwapFree', 0)) // 1024
        
        # Process RSS
        rss_mb = 0
        proc_swap_mb = 0
        try:
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        rss_mb = int(line.split()[1]) // 1024
                    elif line.startswith('VmSwap:'):
                        proc_swap_mb = int(line.split()[1]) // 1024
        except Exception:
            pass
        
        return (f"avail={avail_mb}MB/{total_mb}MB, "
                f"proc_rss={rss_mb}MB, proc_swap={proc_swap_mb}MB, "
                f"sys_swap={swap_used_mb}MB")
    except Exception:
        return "N/A"


def reclaim_memory():
    """Force OS to reclaim freed memory pages.
    
    Python/glibc hold onto freed heap pages in case they're needed again.
    After large deallocations (TFLite unload, etc.), this forces them back
    to the OS immediately instead of waiting for the OS to reclaim them.
    
    Safe to call from any thread. Only affects already-freed memory.
    Called on idle transitions and cleanup paths, never on the detection hot path.
    """
    gc.collect()  # Free Python objects → heap pages freed in glibc
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        libc.malloc_trim(0)  # Return freed heap pages to OS
    except Exception:
        pass
