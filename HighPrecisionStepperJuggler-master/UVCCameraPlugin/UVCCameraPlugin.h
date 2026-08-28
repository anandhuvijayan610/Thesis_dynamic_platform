#pragma once
extern "C" {
    __declspec(dllexport) void* getCamera();

    // Writes the sensor controls through a short-lived DirectShow capture and reports what the
    // driver actually accepted into readback[7] (may be null). Must be called while nothing else
    // holds the camera - i.e. before getCamera(), or after releaseCamera().
    // Order of readback: autoExposure, exposure, gain, saturation, contrast, brightness, gamma.
    __declspec(dllexport) bool applyCameraControls(
        double autoExposure,
        double exposure,
        double gain,
        double saturation,
        double contrast,
        double brightness,
        double gamma,
        double* readback);
    __declspec(dllexport) double getCameraProperty(void* camera, int propertyID);
    __declspec(dllexport) double setCameraProperty(void* camera, int propertyID, double value);
    __declspec(dllexport) void releaseCamera(void* camera);
    // Returns false when the camera produced no frame; the output buffer and the circle
    // globals are then left untouched so the caller can keep showing the previous frame.
    __declspec(dllexport) bool getCameraTexture(
        void* camera,
        unsigned char* data,
        bool executeHT21,
        bool executeMedianBlur,
        int imgMode,            // 0: src, 1: red, 2: green, 3: blue, 4: normalgray, 5: customgray 
        double dp,
        double minDist,
        double param1,
        double param2,
        int minRadius,
        int maxRadius,
        double grayGain,    // multiplies the custom-gray image before blur/Hough; 1.0 = off
        int grayMode        // how the "custom gray" is built - see getCameraTexture in the .cpp
    );
    __declspec(dllexport) double getCircleCenter_x();
    __declspec(dllexport) double getCircleCenter_y();
    __declspec(dllexport) double getCircleRadius();
}