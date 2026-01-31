const { SerialPort } = require('serialport');

async function listPorts() {
    console.log('🔍 Searching for available serial ports...\n');
    
    const ports = await SerialPort.list();
    
    if (ports.length === 0) {
        console.log('❌ No serial ports found!');
        console.log('   Make sure Arduino is connected via USB\n');
        return;
    }
    
    console.log('✅ Found ports:\n');
    ports.forEach((port, index) => {
        console.log(`${index + 1}. ${port.path}`);
        if (port.manufacturer) {
            console.log(`   Manufacturer: ${port.manufacturer}`);
        }
        if (port.serialNumber) {
            console.log(`   Serial: ${port.serialNumber}`);
        }
        console.log('');
    });
    
    console.log('💡 Arduino Uno usually appears as:');
    console.log('   - Windows: COM3, COM4, COM5, etc.');
    console.log('   - Mac: /dev/tty.usbmodem...');
    console.log('   - Linux: /dev/ttyACM0 or /dev/ttyUSB0\n');
    
    console.log('📝 Update ARDUINO_PORT in serial-bridge.js with correct port\n');
}

listPorts();