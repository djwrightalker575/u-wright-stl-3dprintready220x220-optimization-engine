# Install PrusaSlicer CLI on Linux

## Ubuntu/Debian
```bash
sudo apt update
sudo apt install -y prusa-slicer
```

## AppImage
1. Download AppImage from Prusa releases.
2. `chmod +x PrusaSlicer-*.AppImage`
3. Symlink as CLI name:
```bash
sudo ln -s /path/to/PrusaSlicer-*.AppImage /usr/local/bin/prusa-slicer
```

Validate:
```bash
prusa-slicer --help
```
