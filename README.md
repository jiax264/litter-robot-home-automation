# Litter-Robot Monitoring & Alert System

A Python script that monitors Litter-Robot activity and sends automated alerts via email and Slack when anomalies are detected. The system tracks:

- Daily usage patterns - Alerts for abnormally high/low litter box visits  
- Pet weight monitoring - Alerts when average weights fall outside healthy ranges  
- UTI risk monitoring - Alerts extended usage sessions and multiple consecutive attempts 
- Maintenance reminders - Alerts when waste drawer reaches capacity  

The script runs daily via cron job, logging all data to CSV for historical tracking. Historical trends including 3-month litter box usage frequency and daily average weight data can be viewed at [riodash.com](https://riodash.com).

Explore the complete codebase with an auto-generated tutorial covering system architecture, module interactions, and implementation details → [Codebase Tutorial](./Codebase_Tutorial/)
