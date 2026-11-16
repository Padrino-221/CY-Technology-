# CY Technologies Credit Manager for Windows

## Install

1. Install **64-bit CPython 3.14** with the Python launcher if it is missing.
2. Extract the entire ZIP into a writable folder, such as Documents. Keep the extracted files together.
3. Double-click **Install.cmd** and choose a front desk username and password. The bundled Python wheels install without internet access once Python is installed.
4. Double-click **Start.cmd**. The app opens at **http://127.0.0.1:8765/**. Sign in with the account you created. Keep the server window open during use.

The app listens only on this PC and runs under the Windows account that starts it. Start it again after rebooting. If the port is already occupied, close the other instance before retrying. No demonstration accounts, records, or Access files are bundled.

## Back up and restore

Data is stored in **%LOCALAPPDATA%\CY Credit Manager** for the Windows account running the app. The app takes one backup per day on startup. Double-click **Backup.cmd** to take an additional snapshot. Each ZIP under the data folder's **backups** directory contains the database and its referenced photos. Store copies on a protected backup drive as well. Backup ZIPs contain customer data and are not encrypted by the app.

To restore, stop the app. Copy the current data directory to a separate location for safekeeping. Move the current **cy.sqlite3** and **media** out of the data folder and extract the corresponding items from the backup ZIP into the data folder. Start the app and sign in using the credentials from the restored database.

## Scope

This package is for one Windows PC using a browser on the same machine. Office-network or internet access requires a separate deployment with HTTPS and a suitable access configuration. This package starts with an empty database. Access records and photos can be migrated separately.

## Update an existing installation

Stop Credit Manager and run **Backup.cmd** from the current installation. Extract the updated ZIP, then run **Install.cmd** and **Start.cmd** from the updated folder under the same Windows account. The installer applies database changes to the existing local data. The account menu includes **Business settings** for credit terms and follow-up timing.
