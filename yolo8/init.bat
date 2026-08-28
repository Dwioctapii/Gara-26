@echo off
setlocal

title YOLOv8 AMD Radeon Setup

echo ==========================================
echo YOLOv8 AMD RADEON SETUP
echo ==========================================
echo.

echo [1] Detecting Python...

where python
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

python --version

echo.
echo [2] Creating virtual environment...

if not exist venv (
    python -m venv venv
)

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Failed to create venv
    pause
    exit /b 1
)

echo.
echo [3] Activating venv...

call venv\Scripts\activate.bat

echo Python used:
where python
python --version

echo.
echo [4] Updating pip...

python -m pip install --upgrade pip setuptools wheel

echo.
echo [5] Installing YOLO / ONNX / DirectML...

python -m pip install ultralytics
python -m pip install onnx
python -m pip install opencv-python
python -m pip install onnxruntime-directml

echo.
echo ==========================================
echo TESTING
echo ==========================================

python -c "import torch; print('PyTorch:', torch.__version__)"
python -c "import ultralytics; print('Ultralytics:', ultralytics.__version__)"
python -c "import onnxruntime as ort; print('ONNX Runtime:', ort.__version__); print('Providers:', ort.get_available_providers())"

echo.
echo ==========================================
echo DONE
echo ==========================================
pause