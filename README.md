# ORCA - Optical Replication & Control Apparatus

A dynamic lighting system designed for the Cassar Lab to accurately replicate environmental light conditions inside incubation vessels for unbiased nitrogen fixation measurements in marine phytoplankton research. ORCA is a two-part system that automatically modulates light intensity within incubation vessels to match real-time environmental conditions aboard ocean research vessels. The system enables accurate measurement of nitrogen-fixing microorganism activity using the FARACAS technique.

![Project Status](https://img.shields.io/badge/status-in%20development-yellow)
![Hardware](https://img.shields.io/badge/hardware-ESP32%20%7C%20Raspberry%20Pi-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 📋 Table of Contents
- [System Architecture](#system-architecture)
- [Hardware Components](#hardware-components)
- [Design Criteria](#design-criteria)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Testing Plan](#testing-plan)
- [Team](#team)
- [Documentation](#documentation)

## 🏗️ System Architecture

ORCA consists of two interconnected modules:

### Sensor Module (Outdoor)
- Collects environmental light intensity data using dual VEML7700 sensors
- GPS positioning and inclination data via NEO-6M
- ESP32-C3 microcontroller for data processing
- RS-485 communication for reliable long-distance transmission
- IP54 compliant weatherproof enclosure

### Chamber Module (Indoor Lab)
- ESP32-DevKit main controller (updated from Raspberry Pi Zero 2 W)
- PWM-controlled LED strips wrapped around PVC frame
- MOSFET driver for high-power LED control
- User interface with digital display, switches, and potentiometer
- Data logging and web-based control interface
- Multiple connectivity options (USB, Ethernet, WiFi, Bluetooth)

### Communication
- **Primary**: RS-485 differential signaling over standard ethernet cabling (RJ45)

## 🔧 Hardware Components

### Sensor Module
| Component | Model | Purpose |
|-----------|-------|---------|
| Microcontroller | ESP32-C3 (Seeed Studio) | Low-power data processing |
| Light Sensor (Direct) | VEML7700 | Measures up to 120k lux |
| Light Sensor (Diffused) | VEML7700 | Mimics underwater light scattering |
| GPS Module | NEO-6M | Position and inclination data |
| Communication | MAX3485 | RS-485 transceiver |
| Power Regulator | AP63203 | Buck converter (3.3V output) |

### Chamber Module
| Component | Model | Purpose |
|-----------|-------|---------|
| Microcontroller | ESP32-DevKit | Main controller with ADC |
| LED Driver | MOSFET Switch Module | High-power PWM control (400W max) |
| Communication | MAX3485 | RS-485 transceiver |
| Power Regulator | AP63205 | Buck converter (5V output) |
| LDO Regulator | AP2112-3.3 | 3.3V for interface components |
| Display | I2C LCD | Status and manual control |

### PCB Specifications
- **Module PCB**: 45mm × 46mm, 2-layer
- **Chamber PCB**: 45mm × 45mm, 2-layer
- **Trace Width**: 0.35mm standard, 0.5mm for power
- **Copper Density**: 1 oz/sq ft
- **Min Component**: 0402/1005 SMD

## 📊 Design Criteria

Based on extensive client consultation and operational requirements:

| Criteria | Target Metric | Weight |
|----------|---------------|--------|
| **Accuracy of Chamber** | Light ≥10cm from bottle for proper diffusion | 30% |
| **Reliability** | 23+ hours continuous operation, 2+ years minimal maintenance | 25% |
| **Accuracy of Sensor** | Updates every 1-5 minutes, ±15% of verified lux sensor | 20% |
| **Ease of Use** | <5 minute setup, manual & automatic control | 15% |
| **Adaptability** | Wired & wireless capabilities, modular design | 10% |

### Operating Constraints
- **Environmental Protection**: IP54 compliant (dust and water splash resistant)
- **Light Intensity Range**: Full expected range except above safety threshold
- **Power**: Outlet powered with optional solar backup for sensor

## 📁 Repository Structure

```
ORCA-Optical-Replication-Control-Apparatus/
├── hardware/
│   ├── module/
│   │   ├── schematic/           # Module PCB schematics
│   │   ├── pcb/                 # PCB layout files
│   │   └── bom/                 # Bill of materials
│   └── chamber/
│       ├── schematic/           # Chamber PCB schematics
│       ├── pcb/                 # PCB layout files
│       └── bom/                 # Bill of materials
├── firmware/
│   ├── module/                  # ESP32-C3 sensor code
│   └── chamber/                 # ESP32-DevKit control code
├── software/
│   ├── web_interface/           # Web-based control panel
│   └── data_processing/         # Calibration and data logging
├── docs/
│   ├── technical_memos/         # Design documentation
│   ├── testing_plans/           # Validation procedures
│   └── user_manual/             # Setup and operation guide
└── README.md
```

## 🚀 Getting Started

### Prerequisites
- Arduino IDE or PlatformIO
- ESP32 board support package
- Required libraries:
  - Adafruit VEML7700
  - TinyGPS++
  - Wire (I2C)
  - SoftwareSerial

### Hardware Setup
1. **Sensor Module Assembly**
   - Mount ESP32-C3 to custom PCB
   - Connect VEML7700 sensors via I2C
   - Wire NEO-6M GPS module
   - Assemble in IP54 enclosure

2. **Chamber Module Assembly**
   - Mount ESP32-DevKit to routing PCB
   - Connect LED strips to MOSFET driver
   - Wire user interface components
   - Mount on PVC frame structure

3. **Inter-Module Connection**
   - Connect via RJ45 ethernet cable
   - Use T568A or T568B wiring (not crossover)
   - Ensure proper RS-485 termination

### Software Installation
```bash
# Clone repository
git clone https://github.com/yourusername/ORCA-Optical-Replication-Control-Apparatus.git
cd ORCA-Optical-Replication-Control-Apparatus

# Install dependencies (example for PlatformIO)
pio lib install "Adafruit VEML7700"
pio lib install "TinyGPSPlus"

# Upload to sensor module
cd firmware/module
pio run --target upload

# Upload to chamber module
cd ../chamber
pio run --target upload
```

## 🧪 Testing Plan

Our comprehensive testing validates all design criteria:

### 1. Continuous Use Test (Reliability)
- **Duration**: 23 hours continuous operation
- **Trials**: 3 repetitions
- **Metrics**: System failures, measurement standard deviation (<5%), transmission success rate (>90%)

### 2. Sensor Accuracy Test
- **Environments**: Sunny outdoor, cloudy, indoor, lamp, dark
- **Reference**: Hongnew Light Intensity Meter
- **Pass Criteria**: <15% average error, precision ratio <2.0

### 3. Time of Use Test (Ease of Use)
- **Subjects**: 10 EGR101 students
- **Metrics**: Task completion rate (target: >80%)

### 4. Time of Setup Test
- **Target**: <5 minutes
- **Subjects**: 10 individuals
- **Evaluation**: Identify difficult components for improvement

### 5. IP54 Compliance Test
- **Dust Test**: Sand exposure with <1.0mm access probe
- **Water Test**: Weak/medium/strong spray (simulated rain)
- **Trials**: 2 repetitions for reliability

## 👥 Team

**Team Orca** (Duke University)
- Harshith
- Akira
- Michael
- Citlalli

**Faculty Advisors**
- Dr. Kyle
- Dr. Bucholz

**Client**
- Cassar Lab (Dr. Niva, Dr. Merikhi)

## 📚 Documentation

Detailed technical documentation available in `/docs`:
- Problem Statement & Design Criteria
- Solution Evaluation & Pugh Analysis
- Electrical Design Overview
- Testing Procedures & Validation
- User Operation Manual

## 🔄 Development Updates

**2025 November 13th**
- Replaced Raspberry Pi Zero 2 W with ESP32-DevKit for chamber module
- Improved ADC capabilities and resolved GPIO issues
- Updated GPIO wiring documentation

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Cassar Lab for project guidance and domain expertise
- Duke University for resources and support
- Open-source hardware and software communities

## 📞 Contact

For questions or collaboration opportunities, please open an issue or contact the team through the repository.

---

**Note**: This is an active research project. Design specifications may change as development progresses.