using UnityEngine;
using System;
using System.IO.Ports;

namespace HighPrecisionStepperJuggler
{
    public class SerialInterface : MonoBehaviour
    {
        [SerializeField] private string[] _availablePorts;
        [SerializeField] private string _portName = "";

        private SerialPort _port;
        private readonly object _portLock = new object();

        private bool _isOpen
        {
            get
            {
                lock (_portLock)
                {
                    return _port != null && _port.IsOpen;
                }
            }
        }

        private void Awake()
        {
            _availablePorts = SerialPort.GetPortNames();
            // Log available ports and the configured port name for debugging
            Debug.Log("[SerialInterface] Available ports: " + string.Join(", ", _availablePorts));
            Debug.Log("[SerialInterface] Configured port name: " + (_portName == "" ? "(empty)" : _portName));
        }

        // Context menu helper to probe all detected COM ports and try opening them briefly.
        // Use the component's inspector context menu (three-dot menu) and select "Probe Serial Ports".
        [ContextMenu("Probe Serial Ports")]
        public void ProbePorts()
        {
            var ports = SerialPort.GetPortNames();
            if (ports == null || ports.Length == 0)
            {
                Debug.LogWarning("[SerialInterface] No serial ports detected.");
                return;
            }

            Debug.Log("[SerialInterface] Probing ports...");
            foreach (var p in ports)
            {
                try
                {
                    using (var sp = new SerialPort(p, Constants.BaudRate, Parity.None, 8, StopBits.One))
                    {
                        sp.ReadTimeout = 200;
                        sp.WriteTimeout = 200;
                        sp.Open();
                        sp.Close();
                    }
                    Debug.Log($"[SerialInterface] Port {p}: OK (opened and closed)");
                }
                catch (Exception e)
                {
                    Debug.LogWarning($"[SerialInterface] Port {p}: {e.GetType().Name}: {e.Message}");
                }
            }
            Debug.Log("[SerialInterface] Probe complete.");
        }

        private void Open()
        {
            if (string.IsNullOrEmpty(_portName) || _portName.ToLower() == "off")
            {
                Debug.LogWarning("Serial Port Name is invalid. Connection aborted.");
                return;
            }

            lock (_portLock)
            {
                if (_port != null && _port.IsOpen)
                {
                    return;
                }

                try
                {
                    _port = new SerialPort(_portName, Constants.BaudRate, Parity.None, 8, StopBits.One);
                    _port.ReadTimeout = 500;
                    _port.WriteTimeout = 500;
                    _port.Open();
                }
                catch (Exception e)
                {
                    Debug.LogError("Could not open serial port: " + e.Message);
                    Close();
                }
            }
        }

        public void Send(string s)
        {
            if (!_isOpen)
            {
                Open();
            }

            lock (_portLock)
            {
                try
                {
                    // Log outgoing serial messages to help debugging
                    Debug.Log("[SerialInterface] Sending: " + s);

                    if (_port != null && _port.IsOpen)
                    {
                        _port.Write(s);
                        _port.BaseStream.Flush();
                    }
                    else
                    {
                        Debug.LogWarning("Serial port is not open. Message not sent.");
                    }
                }
                catch (Exception e)
                {
                    Debug.LogError("Error sending data: " + e.Message);
                    Close();
                }
            }
        }

        // Helper: send a simple test move to the Arduino (useful from Inspector)
        public void SendTestMove(int motorId = 0, float radians = 0.1f, float duration = 1f)
        {
            // Format: marker:rot1:rot2:rot3:rot4:duration\n
            // Create rotations for four motors; only motorId will get the provided radians
            float[] rots = new float[4] {0f,0f,0f,0f};
            if (motorId >=0 && motorId < 4) rots[motorId] = radians;

            var msg = string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "11.00000:{0:0.00000}:{1:0.00000}:{2:0.00000}:{3:0.00000}:{4:0.00000}\n",
                rots[0], rots[1], rots[2], rots[3], duration);

            Send(msg);
        }

        private void Close()
        {
            lock (_portLock)
            {
                if (_port == null)
                {
                    return;
                }

                try
                {
                    if (_port.IsOpen)
                    {
                        _port.DiscardInBuffer();
                        _port.DiscardOutBuffer();
                        _port.Close();
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("Error closing serial port: " + e.Message);
                }
                finally
                {
                    _port.Dispose();
                    _port = null;
                }
            }
        }

        private void OnDisable()
        {
            Close();
        }

        private void OnDestroy()
        {
            Close();
        }

        private void OnApplicationQuit()
        {
            Close();
        }
    }
}
