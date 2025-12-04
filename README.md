# 🏷️ Code Manager App: QR Code and Barcode Generation & Management

This is a comprehensive desktop application built with **Tkinter** for the GUI and **MySQL Connector** for backend data management. It allows users to **generate, manage, and print** both **QR Codes** and **Code 128 Barcodes**, providing full **CRUD (Create, Read, Update, Delete)** functionality and robust database control.

## ✨ Features Overview

| Category | Feature | Description |
| :--- | :--- | :--- |
| **Code Generation** | **QR Codes** | Generates QR codes for general text, links, and specialized **Wi-Fi configuration** payloads. |
| **Code Generation** | **Code 128 Barcodes** | Generates standard Code 128 barcodes, suitable for alphanumeric data (e.g., inventory tracking). |
| **Data Management** | **MySQL Backend** | Stores code metadata (type, data snippet, file path, creation date) in a configurable MySQL database. |
| **CRUD** | **Atomic Update & Regenerate** | Allows editing of a code's data; the system automatically **regenerates the image** and updates the database record within a transaction for safety. |
| **System** | **Configuration** | Uses a `config.ini` file for easy management of MySQL connection settings. |
| **System** | **DB Utilities** | Includes buttons for **Database Setup/Table Creation**, **Database Backup** (using `mysqldump`), and a **DANGER ZONE** for complete database deletion. |
| **Output** | **Printing** | Supports cross-platform printing of generated code images to system printers (Windows `os.startfile`, Linux/macOS `lpr`). |
| **Output** | **View & Export** | Allows viewing of generated images in a pop-up and exporting the image file to a custom location. |

## ⚙️ Prerequisites

Before running the application, ensure you have the following installed:

1.  **Python 3.x**
2.  **MySQL Server** (accessible locally or via network).
3.  **Required Python Libraries:**
    ```bash
    pip install mysql-connector-python tk qrcode python-barcode Pillow
    # Optional: For better Windows printer control
    pip install pywin32 
    ```
4.  **PATH Configuration (Optional but Recommended):** For the "Backup Database" feature to work, the directory containing the `mysqldump` executable (usually in your MySQL/XAMPP `bin` folder) must be added to your system's environment PATH.

## 🚀 Getting Started

1.  **Clone the repository** (or save the provided Python file).
2.  **Run the application:**
    ```bash
    python code_manager_app.py
    ```

3.  **Configure Database:**
    * The application will create a default `config.ini` file if it doesn't exist.
    * Navigate to the **Database Setup/Backup** tab.
    * Enter your MySQL connection details (Host, User, Password, Database Name).
    * Click "**Save & Test Settings**".

4.  **Initialize Database:**
    * Click "**Setup Database & Tables**". This will create the database (if it doesn't exist) and the required tables: `created_codes` and `scanned_codes`.

5.  **Start Generating Codes:**
    * Move to the **Create Code** tab to generate and save new QR Codes or Barcodes.

## 📁 Project Structure
