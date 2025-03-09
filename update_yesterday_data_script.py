#!/usr/bin/env python
# coding: utf-8

# In[ ]:

import asyncio
from pylitterbot import Account
import pandas as pd
import os
import smtplib
from email.mime.text import MIMEText
import sys

sender_email = os.environ["LITTER_ROBOT_USERNAME"]
sender_password = os.environ["GMAIL_PASSWORD"]

def send_email(subject, message):
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = sender_email
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server: 
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, sender_email, msg.as_string())

async def main():
    try:
        account = Account()
        await account.connect(
            username=os.environ["LITTER_ROBOT_USERNAME"],
            password=os.environ["LITTER_ROBOT_PASSWORD"],
            load_robots=True
        )
        activities = await account.robots[0].get_activity_history(limit=300)
        await account.disconnect()
    except Exception as e:
        send_email("LR4 Data Warning", "API returned an error: " + str(e))
        sys.exit(1) 

    df = pd.DataFrame({
        'Timestamp': [act.timestamp for act in activities],
        'Activity': [str(act.action) for act in activities]
    })
    df['DateTime'] = df['Timestamp'].dt.tz_convert('America/New_York')
    yesterday = pd.Timestamp.now(tz='America/New_York').date() - pd.Timedelta(days=1)
    df = df[df['DateTime'].dt.date == yesterday][['DateTime', 'Activity']]
    df = df.iloc[:2]

    if len(df) <= 4:
        send_email("LR4 Data Warning", "Bruno used the litter box <=1 time yesterday!")
        sys.exit(1) 
    
    mapping = {
        'LitterBoxStatus.CAT_SENSOR_INTERRUPTED': 'Cycle Interrupted',
        'LitterBoxStatus.CAT_DETECTED': 'Cat Detected',
        'LitterBoxStatus.CLEAN_CYCLE': 'Clean Cycle In Progress',
        'LitterBoxStatus.CLEAN_CYCLE_COMPLETE': 'Clean Cycle Complete'
    }
    df['Activity'] = df['Activity'].map(mapping).fillna(df['Activity'])
    weights = df['Activity'].str.extract(r'Pet Weight Recorded: (\d+\.?\d*) lbs')[0]
    mask = weights.notna()
    df.loc[mask, 'Activity'] = 'Weight Recorded'
    df.loc[mask, 'Value'] = weights[mask].astype(float)
    df.sort_values('DateTime', inplace=True)
    df.to_csv("master_lr4_practice.csv", mode='a', header=False, index=False)

if __name__ == '__main__':
    asyncio.run(main())

