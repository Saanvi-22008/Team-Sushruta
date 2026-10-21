from urllib.request import urlopen

with urlopen("http://127.0.0.1:8080/api/healthz", timeout=2) as response:
    if response.status != 200:
        raise SystemExit(1)
