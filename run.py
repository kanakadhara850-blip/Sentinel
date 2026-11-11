"""One-command launcher:  python run.py
Starts backend (TCP :9009, API :8000) and frontend (http://localhost:3000), opens the browser."""
import os, subprocess, sys, time, webbrowser
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "backend")
WS = "ws://localhost:8000/ws/events"

def main():
    if not os.path.isfile(os.path.join(BACKEND, "artifacts", "current.json")):
        print("No trained model found - training one (one-time)...")
        subprocess.check_call([sys.executable, "-m", "app.models.train", "--n", "20000"], cwd=BACKEND)
    procs = [
        subprocess.Popen([sys.executable, "-m", "app.main"], cwd=BACKEND),
        subprocess.Popen([sys.executable, os.path.join(HERE, "frontend_server.py"), "3000"]),
    ]
    time.sleep(4)
    url = f"http://localhost:3000/login?ws={WS}"
    print(f"\nFrontend : http://localhost:3000\nLive mode: {url}\nAPI docs : http://localhost:8000/docs\n"
          "Login    : admin@sentinel.demo / sentinel-demo\nCtrl+C to stop.\n")
    webbrowser.open(url)
    try:
        for p in procs: p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()

if __name__ == "__main__":
    main()
