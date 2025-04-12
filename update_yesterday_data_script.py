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
import requests

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

def send_slack_message(message):
    token = os.environ["SLACK_BOT_TOKEN"]
    headers = {'Authorization': f'Bearer {token}'}
    email = os.environ["SLACK_EMAIL"]
    params = {'email': email}
    response = requests.get('https://slack.com/api/users.lookupByEmail', headers=headers, params=params)
    user_id = response.json()['user']['id']
    data = {'users': user_id}
    conv_resp = requests.post('https://slack.com/api/conversations.open', headers=headers, json=data)
    channel_id = conv_resp.json()['channel']['id']
    msg_data = {'channel': channel_id, 'text': message}
    requests.post('https://slack.com/api/chat.postMessage', headers=headers, json=msg_data)

async def main():
    try:
        account = Account()
        await account.connect(
            username=os.environ["LITTER_ROBOT_USERNAME"],
            password=os.environ["LITTER_ROBOT_PASSWORD"],
            load_robots=True
        )
        activities = await account.robots[0].get_activity_history(limit=300)
        waste_percent = account.robots[0].waste_drawer_level
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

    num_visit = int((df['Activity'] == 'Clean Cycle In Progress').sum())
    msg_parts = []

    waste_percent = 90
    num_visit = 2

    if waste_percent >= 80:
        msg_parts.append(f"Waste backet is {waste_percent}% full. Please change ASAP.")
    if num_visit >= 6 or num_visit <= 2:
        msg_parts.append(f":poop: Cat used bathroom {num_visit} times yesterday. Please monitor.")

    if msg_parts:
        send_slack_message("\n".join(msg_parts))

if __name__ == '__main__':
    asyncio.run(main())

