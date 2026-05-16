import platform

# Python 3.14 Windows Hang Fix
# platform.system() and related calls hang indefinitely in this environment.
if not hasattr(platform, '_monkeypatched'):
    print("Applying platform monkeypatch for Python 3.14 on Windows...")
    platform.system = lambda: "Windows"
    platform.release = lambda: "10"
    platform.version = lambda: "10.0.19041"
    platform.python_version = lambda: "3.14.3"
    platform.machine = lambda: "AMD64"
    platform.processor = lambda: "Intel64 Family 6 Model 158 Stepping 10, GenuineIntel"
    platform._monkeypatched = True
