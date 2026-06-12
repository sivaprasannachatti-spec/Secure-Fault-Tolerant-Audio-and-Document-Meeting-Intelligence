import os
import platform

# Python 3.14 Windows Hang Fix
# platform.system() and related calls hang indefinitely in this environment.
if os.name == 'nt' and not hasattr(platform, '_monkeypatched'):
    print("Applying platform monkeypatch for Python 3.14 on Windows...")
    platform.system = lambda: "Windows"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    platform.python_version = lambda: "3.14.3"
    platform.machine = lambda: "AMD64"
    platform.processor = lambda: "Intel64 Family 6 Model 158 Stepping 10, GenuineIntel"
    platform._monkeypatched = True

import os
# Prevent OpenBLAS/MKL memory allocation crashes by restricting thread counts
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

# Set default DB_FILE to prevent KeyError and ensure Vercel uses /tmp (read-only filesystem workaround)
if os.environ.get('VERCEL'):
    # Force the DB path to be inside /tmp to avoid read-only filesystem crash
    configured_db = os.environ.get('DB_FILE', 'offline_queue.db')
    db_filename = os.path.basename(configured_db)
    os.environ['DB_FILE'] = os.path.join('/tmp', db_filename)
    
    os.environ.setdefault('JWT_SECRET_KEY', 'default_secret_key_for_meeting_intelligence')
    os.environ.setdefault('SUPABASE_PROJECT_URL', 'https://placeholder-project.supabase.co')
    os.environ.setdefault('SUPABASE_API_KEY', 'placeholder-anon-key')
else:
    os.environ.setdefault('DB_FILE', 'offline_queue.db')
    os.environ.setdefault('JWT_SECRET_KEY', 'default_secret_key_for_meeting_intelligence')
