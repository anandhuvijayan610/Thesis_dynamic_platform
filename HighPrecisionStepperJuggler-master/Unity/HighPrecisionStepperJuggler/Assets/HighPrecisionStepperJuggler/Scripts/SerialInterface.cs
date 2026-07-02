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
        private bool _isOpen => _port != null && _port.IsOpen;

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

            try
            {
                _port = new SerialPort(_portName, Constants.BaudRate, Parity.None, 8, StopBits.One);
                _port.ReadTimeout = 500; // MUST have a timeout to prevent thread locking
                _port.WriteTimeout = 500;
                _port.Open();

                _receiveDataThread = new Thread(RecieveData);
                _receiveDataThread.IsBackground = true; // Makes the thread close when Unity closes
                _receiveDataThread.Start();
            }
            catch (System.Exception e)
            {
                Debug.LogError("Could not open serial port: " + e.Message);
            }
        }

        public void Send(string s)
        {
            if (!_isOpen) Open();
            
            _port.Write(s);
        }
        
        private void RecieveData()
        {
            while (_port.IsOpen)
            {
                var str = _port.ReadLine();
            }
        }

        private void OnDestroy()
        {
            if (_port != null && _port.IsOpen)
            {
                _port.Close();
            }

            if (_receiveDataThread != null && _receiveDataThread.IsAlive)
            {
                _receiveDataThread.Abort();
            }
        }
    }
}
