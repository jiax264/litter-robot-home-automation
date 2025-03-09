{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": null,
   "id": "08f9af14-c3e0-4510-ae65-47c20a91eb31",
   "metadata": {},
   "outputs": [],
   "source": [
    "import nest_asyncio\n",
    "import asyncio\n",
    "from pylitterbot import Account\n",
    "import pandas as pd\n",
    "import os\n",
    "\n",
    "nest_asyncio.apply()\n",
    "\n",
    "async def main():\n",
    "    account = Account()\n",
    "    await account.connect(username=\"jiax264@gmail.com\",\n",
    "                          password=\"Idolove$mart2\",\n",
    "                          load_robots=True)\n",
    "    activities = await account.robots[0].get_activity_history(limit=300)\n",
    "    await account.disconnect()\n",
    "\n",
    "    df = pd.DataFrame({\n",
    "        'Timestamp': [act.timestamp for act in activities],\n",
    "        'Activity': [str(act.action) for act in activities]\n",
    "    })\n",
    "    df['DateTime'] = df['Timestamp'].dt.tz_convert('America/New_York')\n",
    "    today = pd.Timestamp.now(tz='America/New_York').date()\n",
    "    df = df[df['DateTime'].dt.date == today][['DateTime', 'Activity']]\n",
    "    mapping = {\n",
    "        'LitterBoxStatus.CAT_SENSOR_INTERRUPTED': 'Cycle Interrupted',\n",
    "        'LitterBoxStatus.CAT_DETECTED': 'Cat Detected',\n",
    "        'LitterBoxStatus.CLEAN_CYCLE': 'Clean Cycle In Progress',\n",
    "        'LitterBoxStatus.CLEAN_CYCLE_COMPLETE': 'Clean Cycle Complete'\n",
    "    }\n",
    "    df['Activity'] = df['Activity'].map(mapping).fillna(df['Activity'])\n",
    "    weights = df['Activity'].str.extract(r'Pet Weight Recorded: (\\d+\\.?\\d*) lbs')[0]\n",
    "    mask = weights.notna()\n",
    "    df.loc[mask, 'Activity'] = 'Weight Recorded'\n",
    "    df.loc[mask, 'Value'] = weights[mask].astype(float)\n",
    "    df.sort_values('DateTime', inplace=True)\n",
    "    df.to_csv(\"master_lr4_practice.csv\", mode='a', header=False, index=False)\n",
    "\n",
    "if __name__ == '__main__':\n",
    "    asyncio.run(main())"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python [conda env:.conda-litter_robot] *",
   "language": "python",
   "name": "conda-env-.conda-litter_robot-py"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.10.15"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
