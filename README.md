# DirectP2P LAB (separate GitHub build branch)

This branch contains the Android + Python direct UDP P2P project as a versioned compressed source snapshot `directp2p-project.tar.xz`.

Extract the complete sources:

```bash
tar -xJf directp2p-project.tar.xz
cd directp2p-lab
python3 -m unittest discover -s tests -v
python3 python/rendezvous.py --bind 0.0.0.0 --port 34781
```

The `DirectP2P Android APK` GitHub Actions workflow runs both Python tests and a native Android APK build. The real game traffic travels directly between peers, never through the rendezvous server. Players do not need public IPv4, but the discovery server must be publicly UDP-reachable for cross-network matchmaking. This first prototype only supports IPv4 and cannot bypass every carrier NAT.
