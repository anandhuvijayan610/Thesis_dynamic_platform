#include "UVCCameraPlugin.h"
#include <opencv2/opencv.hpp>
#include <cstdio>
#include "opencv2/imgcodecs.hpp"
#include "opencv2/highgui.hpp"
#include "opencv2/imgproc.hpp"

using namespace cv;
using namespace std;

void* getCamera()
{
    // Pinned to MSMF rather than left to CAP_ANY's backend ordering. Measured on the target
    // camera: MSMF sustains a real 120fps at its native 480x640, while CAP_DSHOW cannot leave
    // YUY2 and tops out at 30fps. MSMF also needs no MJPG request - CAP_PROP_FOURCC is a no-op
    // on it, and 120fps is reached without one.
    // NOTE: this requires OpenCV >= ~4.5. The OpenCV 4.2 build this plugin originally linked
    // against enabled MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, which hides the camera's
    // compressed modes from MSMF and pinned it to NV12 at 20fps.
    auto cap = new cv::VideoCapture(0, cv::CAP_MSMF);

    return static_cast<void*>(cap);
}

// OpenCV's MSMF backend silently ignores every sensor control on this camera - measured
// directly: set() is a no-op and the readback never moves off the driver defaults, whatever
// order the calls are made in. Its DirectShow backend *does* apply them, and the values persist
// in the driver into the MSMF stream opened afterwards (confirmed: writing gain through DSHOW
// visibly changes the brightness of the subsequent MSMF stream). MSMF is still the only backend
// that reaches 120fps here, so controls are written through a throwaway DSHOW capture and the
// real stream is then opened on MSMF.
// NOTE: DSHOW and MSMF report their own independent values for these properties, so the numbers
// read back here will NOT match what getCameraProperty() reports on the streaming capture. Trust
// this readback for what was applied, and the image itself for whether it helped.
bool applyCameraControls(
    double autoExposure,
    double exposure,
    double gain,
    double saturation,
    double contrast,
    double brightness,
    double gamma,
    double* readback)
{
    cv::VideoCapture ctrl(0, cv::CAP_DSHOW);
    if (!ctrl.isOpened())
    {
        return false;
    }

    ctrl.set(cv::CAP_PROP_AUTO_EXPOSURE, autoExposure);
    ctrl.set(cv::CAP_PROP_EXPOSURE, exposure);
    ctrl.set(cv::CAP_PROP_GAIN, gain);
    ctrl.set(cv::CAP_PROP_SATURATION, saturation);
    ctrl.set(cv::CAP_PROP_CONTRAST, contrast);
    ctrl.set(cv::CAP_PROP_BRIGHTNESS, brightness);
    ctrl.set(cv::CAP_PROP_GAMMA, gamma);

    if (readback != nullptr)
    {
        readback[0] = ctrl.get(cv::CAP_PROP_AUTO_EXPOSURE);
        readback[1] = ctrl.get(cv::CAP_PROP_EXPOSURE);
        readback[2] = ctrl.get(cv::CAP_PROP_GAIN);
        readback[3] = ctrl.get(cv::CAP_PROP_SATURATION);
        readback[4] = ctrl.get(cv::CAP_PROP_CONTRAST);
        readback[5] = ctrl.get(cv::CAP_PROP_BRIGHTNESS);
        readback[6] = ctrl.get(cv::CAP_PROP_GAMMA);
    }

    ctrl.release();
    return true;
}

double getCameraProperty(void* camera, int propertyID) 
{
    auto cap = static_cast<cv::VideoCapture*>(camera);
    return cap->get(propertyID);
}

double setCameraProperty(void* camera, int propertyID, double value) 
{
    auto cap = static_cast<cv::VideoCapture*>(camera);
    return cap->set(propertyID, value);
}

void releaseCamera(void* camera)
{
    auto cap = static_cast<cv::VideoCapture*>(camera);
    delete cap;
}

double center_x = 0.0;
double center_y = 0.0;
double radius = 0.0;

bool getCameraTexture(
    void* camera,
    unsigned char* data,
    bool executeHT21,
    bool executeMedianBlur,
    int imgMode,            // 0: src, 1: red, 2: green, 3: blue, 4: normalgray, 5: customgray 6: customgrayWithCircleOverlay
    double dp,
    double minDist,
    double param1,
    double param2,
    int minRadius,
    int maxRadius,
    double grayGain,
    int grayMode)
{
    auto cap = static_cast<cv::VideoCapture*>(camera);

    cv::Mat img;
    *cap >> img;

    // A dropped grab yields an empty Mat; split() below would then throw straight through the
    // P/Invoke boundary and take the Unity process down with it.
    if (img.empty())
    {
        return false;
    }

    Mat src = img;

    Mat bgr[3];
    split(src, bgr);
    Mat r = Mat(src.rows, src.cols, CV_8U, bgr[2].data);
    Mat g = Mat(src.rows, src.cols, CV_8U, bgr[1].data);
    Mat b = Mat(src.rows, src.cols, CV_8U, bgr[0].data);

    Mat gray;
    Mat normalGray;

	if (imgMode == 4)
    {
        cv::cvtColor(src, normalGray, COLOR_BGR2GRAY);
    }
    if (grayMode == 2)
    {
        // SATURATION x DARKNESS. The most reliable discriminator measured on this rig, because
        // the ball is both more saturated AND darker than the background:
        //   ball  saturation 80.8, value 100.6
        //   bg    saturation 32.2, value 144.7
        // Hue is useless for separating them - the background's hue reads 74.8 on average but
        // ranges 9..171, i.e. it is near-neutral so its hue is meaningless noise, and a warm
        // tan/wooden background lands in the SAME hue band as an orange ball, which is what makes
        // grayMode 1 light up the background instead of the ball.
        // Measured against a real ball frame: 98.3% of the ball above threshold, 9.4% background
        // false-positives, blob radius 93.4 (true 95), circularity 0.83 - the best of everything
        // tried (hue-gated: 79.8%/5.8%/0.76; saturation alone: 94.7%/22.3%/0.80).
        cv::Mat hsv;
        cv::cvtColor(src, hsv, cv::COLOR_BGR2HSV);

        cv::Mat saturation, value;
        cv::extractChannel(hsv, saturation, 1);
        cv::extractChannel(hsv, value, 2);

        cv::Mat darkness;
        cv::subtract(cv::Scalar(255.0), value, darkness);

        cv::multiply(saturation, darkness, gray, 1.0 / 255.0, CV_8U);
    }
    else if (grayMode == 1)
    {
        // Illumination-robust alternative to r-b. The ball is lit from the ceiling side, so the
        // face pointing at the camera sits in shadow and reads dark brown rather than orange -
        // which collapses r-b even though the HUE is still orange. Gating saturation by hue keeps
        // the shadowed part of the ball while rejecting the neutral ceiling.
        // Measured on a real backlit frame: r-b covered 49% of the ball with 13% background
        // false-positives and a thresholded-blob circularity of 0.05; this metric covered 54%
        // with 4.7% background and circularity 0.57 - i.e. an actual disc, which is what the
        // border-tracing detector in ImageProcessing.cs needs in order to close a contour.
        cv::Mat hsv;
        cv::cvtColor(src, hsv, cv::COLOR_BGR2HSV);

        // OpenCV hue is 0..179, and orange/red wraps around 0, so it takes two ranges.
        cv::Mat lowMask, highMask, hueMask;
        cv::inRange(hsv, cv::Scalar(0, 0, 0), cv::Scalar(30, 255, 255), lowMask);
        cv::inRange(hsv, cv::Scalar(166, 0, 0), cv::Scalar(180, 255, 255), highMask);
        cv::bitwise_or(lowMask, highMask, hueMask);

        cv::Mat saturation;
        cv::extractChannel(hsv, saturation, 1);

        gray = cv::Mat::zeros(src.size(), CV_8U);
        saturation.copyTo(gray, hueMask);
    }
    else
    {
        // grayMode 0: the original red-minus-blue. Weakest of the three here - it collapses
        // wherever the ball is in shadow, because a shadowed orange ball reads dark brown.
        gray = r - b;
    }

    // The r-b "custom gray" separates the ball from the ceiling by only about 9 grey levels on
    // this rig - measured on a real ball frame: ball R-B = +10.8, background R-B = -6.1, and the
    // unsigned subtraction floors that negative background at 0. Far too weak to push gradients
    // past HoughCircles' param1=60, so scale it before the blur.
    // Measured on that same frame: gain 1 finds nothing at all, gain 3 locks onto the ball within
    // 24px. Do not raise this casually - Hough's cost climbs steeply with the extra edge pixels
    // (gain 3 + maxRadius 150 = 10ms/frame, but gain 4 + maxRadius 200 = 52ms, i.e. ~19fps).
    if (grayGain != 1.0)
    {
        gray = gray * grayGain;
    }

    if (executeMedianBlur)
    {
        medianBlur(gray, gray, 5);
    }

    if (executeHT21)
    {
        vector<Vec3f> circles;
        HoughCircles(
            gray,             // inputArray
            circles,          // outputArray
            HOUGH_GRADIENT,   // method
            dp,               // dp
            minDist,          // minDist
            param1,           // param1
            param2,           // param2
            minRadius,        // minRadius
            maxRadius         // maxRadius
        );

        if(circles.size() > 0)
        {
            Vec3i c = circles[0];
            center_x = (double)c[0];
            center_y = (double)c[1];
            radius = (double)c[2];
        }
        else
        {
            center_x = 0.0;
            center_y = 0.0;
            radius = 0.0;
        }

        if (imgMode == 6)
        {
            for (size_t i = 0; i < circles.size(); i++)
            {
                Vec3i c = circles[i];
                Point center = Point(c[0], c[1]);
                int radius = c[2];

				circle(gray, center, 1, Scalar(0, 100, 100), 3, LINE_AA);
				circle(gray, center, radius, Scalar(255, 0, 255), 3, LINE_AA);
            }
        }
    }

    // 0: src, 1: red, 2: green, 3: blue, 4: normalgray, 5: customgray
    cv::Mat rgba;
    if (imgMode == 0)
    {
        cv::cvtColor(src, rgba, cv::COLOR_BGR2RGBA);
    }
    else if (imgMode == 1)
    {
        cv::cvtColor(r, rgba, cv::COLOR_GRAY2RGBA);
    }
    else if (imgMode == 2)
    {
        cv::cvtColor(g, rgba, cv::COLOR_GRAY2RGBA);
    }
    else if (imgMode == 3)
    {
        cv::cvtColor(b, rgba, cv::COLOR_GRAY2RGBA);
    }
    else if (imgMode == 4)
    {
        cv::cvtColor(normalGray, rgba, cv::COLOR_GRAY2RGBA);
    }
    else if (imgMode == 5 || imgMode == 6)
    {
        cv::cvtColor(gray, rgba, cv::COLOR_GRAY2RGBA);
    }
    std::memcpy(data, rgba.data, rgba.total() * rgba.elemSize());
    return true;
}

double getCircleCenter_x()
{
    return center_x;
}

double getCircleCenter_y()
{
    return center_y;
}

double getCircleRadius()
{
    return radius;
}
