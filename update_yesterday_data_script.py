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


class Config:
    """Configuration constants for the litter robot monitor."""

    # Activity thresholds
    LOW_USAGE_THRESHOLD = 4
    HIGH_USAGE_THRESHOLD = 9

    # Weight thresholds (in pounds)
    MIN_HEALTHY_WEIGHT = 8.5
    MAX_HEALTHY_WEIGHT = 9.1
    MIN_VALID_WEIGHT = 7.5  
    MAX_VALID_WEIGHT = 9.5

    # Waste level threshold (percentage)
    WASTE_ALERT_THRESHOLD = 75

    # API limits
    ACTIVITY_HISTORY_LIMIT = 300

    # Email configuration
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    SMTP_TIMEOUT = 30

    # Timezone
    TIMEZONE = "America/New_York"

    # File paths
    CSV_OUTPUT_FILE = "master_lr4_practice.csv"


class LitterRobotMonitor:
    """Monitor litter robot activity and send alerts for anomalies."""

    def __init__(self):
        """Initialize the monitor with environment variables."""
        self.sender_email = os.environ["LITTER_ROBOT_USERNAME"]
        self.sender_password = os.environ["GMAIL_PASSWORD"]
        self.litter_robot_password = os.environ["LITTER_ROBOT_PASSWORD"]
        self.slack_token = os.environ["SLACK_BOT_TOKEN"]
        self.slack_email = os.environ["SLACK_EMAIL"]

    def send_email(self, subject: str, message: str) -> None:
        """Send email notification."""
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = self.sender_email
        msg["To"] = self.sender_email

        with smtplib.SMTP(
            Config.SMTP_SERVER, Config.SMTP_PORT, timeout=Config.SMTP_TIMEOUT
        ) as server:
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.sendmail(self.sender_email, self.sender_email, msg.as_string())

    def send_slack_message(self, message: str) -> None:
        """Send message to Slack."""
        headers = {"Authorization": f"Bearer {self.slack_token}"}
        params = {"email": self.slack_email}

        response = requests.get(
            "https://slack.com/api/users.lookupByEmail", headers=headers, params=params
        )
        user_id = response.json()["user"]["id"]

        data = {"users": user_id}
        conv_resp = requests.post(
            "https://slack.com/api/conversations.open", headers=headers, json=data
        )
        channel_id = conv_resp.json()["channel"]["id"]

        msg_data = {"channel": channel_id, "text": message}
        requests.post(
            "https://slack.com/api/chat.postMessage", headers=headers, json=msg_data
        )

    def _extract_and_update_values(
        self, df: pd.DataFrame, pattern: str, activity_name: str, dtype: type
    ) -> None:
        """Extract values from activity strings and update DataFrame."""
        values = df["Activity"].str.extract(pattern)[0]
        mask = values.notna()
        df.loc[mask, "Activity"] = activity_name
        df.loc[mask, "Value"] = values[mask].astype(dtype)

    async def main(self) -> None:
        try:
            account = Account()
            await account.connect(
                username=self.sender_email,
                password=self.litter_robot_password,
                load_robots=True,
            )
            activities = await account.robots[0].get_activity_history(
                limit=Config.ACTIVITY_HISTORY_LIMIT
            )
            waste_percent = account.robots[0].waste_drawer_level
            await account.disconnect()
        except Exception as e:
            self.send_email("LR4 Data Warning", "API returned an error: " + str(e))
            sys.exit(1)

        df = pd.DataFrame(
            {
                "Timestamp": [act.timestamp for act in activities],
                "Activity": [str(act.action) for act in activities],
            }
        )
        df["DateTime"] = df["Timestamp"].dt.tz_convert(Config.TIMEZONE)
        yesterday = pd.Timestamp.now(tz=Config.TIMEZONE).date() - pd.Timedelta(days=1)
        df = df[df["DateTime"].dt.date == yesterday][["DateTime", "Activity"]]

        if len(df) <= Config.LOW_USAGE_THRESHOLD:
            self.send_email(
                "LR4 Data Warning",
                "Bruno & Murano used the litter box <=1 time yesterday!",
            )
            sys.exit(1)

        mapping = {
            "LitterBoxStatus.CAT_SENSOR_INTERRUPTED": "Cycle Interrupted",
            "LitterBoxStatus.CAT_DETECTED": "Cat Detected",
            "LitterBoxStatus.CLEAN_CYCLE": "Clean Cycle In Progress",
            "LitterBoxStatus.CLEAN_CYCLE_COMPLETE": "Clean Cycle Complete",
        }
        df["Activity"] = df["Activity"].map(mapping).fillna(df["Activity"])

        self._extract_and_update_values(
            df, r"Pet Weight Recorded: (\d+\.?\d*) lbs", "Weight Recorded", float
        )
        self._extract_and_update_values(df, r"Clean Cycles: (\d+)", "Clean Cycles", int)

        df.sort_values("DateTime", inplace=True)
        df.to_csv(Config.CSV_OUTPUT_FILE, mode="a", header=False, index=False)

        num_visit = int((df["Activity"] == "Clean Cycle In Progress").sum())
        msg_parts = []

        if waste_percent >= Config.WASTE_ALERT_THRESHOLD:
            msg_parts.append(
                f"Waste backet is {waste_percent}% full. Please change ASAP."
            )
        if (
            num_visit >= Config.HIGH_USAGE_THRESHOLD
            or num_visit <= Config.LOW_USAGE_THRESHOLD
        ):
            msg_parts.append(
                f":poop: Cats used bathroom {num_visit} times yesterday. Please monitor."
            )

        weight_data = df[df["Activity"] == "Weight Recorded"]["Value"].dropna()
        if len(weight_data) > 0:
            filtered_weight_data = weight_data[
                (weight_data >= Config.MIN_VALID_WEIGHT) & 
                (weight_data <= Config.MAX_VALID_WEIGHT)
            ]
            
            if len(filtered_weight_data) > 0:
                avg_weight = filtered_weight_data.mean()
                if (
                    avg_weight <= Config.MIN_HEALTHY_WEIGHT
                    or avg_weight >= Config.MAX_HEALTHY_WEIGHT
                ):
                    msg_parts.append(
                        f"Avg Weight yesterday = {avg_weight:.1f} lbs. Please investigate."
                    )

        if msg_parts:
            self.send_slack_message("\n".join(msg_parts))


async def main():
    monitor = LitterRobotMonitor()
    await monitor.main()


if __name__ == "__main__":
    asyncio.run(main())
