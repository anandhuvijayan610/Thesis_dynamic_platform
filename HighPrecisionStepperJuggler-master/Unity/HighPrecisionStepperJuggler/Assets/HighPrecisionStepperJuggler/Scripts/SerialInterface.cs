using UnityEngine;
using System.IO.Ports;
using System.Threading;

namespace HighPrecisionStepperJuggler
{
    public class SerialInterface : MonoBehaviour
    {
        [SerializeField] private string[] _availablePorts;
        [SerializeField] private string _portName = "";
        
        private SerialPort _port;
        Thread _receiveDataThread;
        private bool _shouldExit = false;
        private readonly object _portLock = new object(); // Thread safety lock
        
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
        }

        private void Open()
        {
            // SAFETY CHECK: Don't try to open if the name is blank or invalid
            if (string.IsNullOrEmpty(_portName) || _portName.ToLower() == "off")
            {
                Debug.LogWarning("Serial Port Name is invalid. Connection aborted.");
                return;
            }

            lock (_portLock)
            {
                try
                {
                    _port = new SerialPort(_portName, Constants.BaudRate, Parity.None, 8, StopBits.One);
                    _port.ReadTimeout = 500; // MUST have a timeout to prevent thread locking
                    _port.WriteTimeout = 500;
                    _port.Open();

                    _shouldExit = false;
                    _receiveDataThread = new Thread(RecieveData);
                    _receiveDataThread.IsBackground = true; // Makes the thread close when Unity closes
                    _receiveDataThread.Start();
                }
                catch (System.Exception e)
                {
                    Debug.LogError("Could not open serial port: " + e.Message);
                }
            }
        }

        public void Send(string s)
        {
            if (!_isOpen) Open();
            
            lock (_portLock)
            {
                try
                {
                    if (_port != null && _port.IsOpen)
                    {
                        _port.Write(s);
                    }
                }
                catch (System.Exception e)
                {
                    Debug.LogError("Error sending data: " + e.Message);
                }
            }
        }
        
        private void RecieveData()
        {
            while (!_shouldExit)
            {
                try
                {
                    lock (_portLock)
                    {
                        if (_port != null && _port.IsOpen)
                        {
                            var str = _port.ReadLine();
                            // TODO: Process received data here if needed
                        }
                    }
                }
                catch (TimeoutException)
                {
                    // Timeout is expected when no data is available - just continue
                    continue;
                }
                catch (System.Exception e)
                {
                    Debug.LogError("Error receiving data: " + e.Message);
                    break;
                }
            }
        }

        private void OnDestroy()
        {
            _shouldExit = true;
            
            lock (_portLock)
            {
                if (_port != null && _port.IsOpen)
                {
                    _port.Close();
                    _port.Dispose();
                }
            }

            if (_receiveDataThread != null && _receiveDataThread.IsAlive)
            {
                _receiveDataThread.Join(1000); // Wait up to 1 second for thread to finish
            }
        }
    }
}
