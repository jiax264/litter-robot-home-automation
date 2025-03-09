#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import nest_asyncio
import asyncio
from pylitterbot import Account
import pandas as pd
import os

nest_asyncio.apply()

async def main():
    account = Account()
    await account.connect(username="jiax264@gmail.com",
                          password="Idolove$mart2",
                          load_robots=True)
    activities = await account.robots[0].get_activity_history(limit=300)
    await account.disconnect()

    df = pd.DataFrame({
        'Timestamp': [act.timestamp for act in activities],
        'Activity': [str(act.action) for act in activities]
    })
    df['DateTime'] = df['Timestamp'].dt.tz_convert('America/New_York')
    today = pd.Timestamp.now(tz='America/New_York').date()
    df = df[df['DateTime'].dt.date == today][['DateTime', 'Activity']]
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

