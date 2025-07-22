#!/usr/bin/env python
# coding: utf-8

import asyncio
import os
import smtplib
import sys
from datetime import timedelta
from email.mime.text import MIMEText
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import requests
from pylitterbot import Account


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

    # Cycle timing thresholds
    CYCLE_DELAY = 7  # minutes
    USAGE_DURATION = 5  # minutes
    CONSECUTIVE_WEIGHT_THRESHOLD = 3  # number of consecutive weight recordings


class NotificationService:
    """Handles email and Slack notifications."""

    def __init__(self, sender_email: str, sender_password: str,
                 slack_token: str, slack_email: str):
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.slack_token = slack_token
        self.slack_email = slack_email

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
        user_id = self._get_slack_user_id()
        channel_id = self._open_slack_conversation(user_id)
        self._post_slack_message(channel_id, message)

    def _get_slack_user_id(self) -> str:
        """Get Slack user ID from email."""
        headers = {"Authorization": f"Bearer {self.slack_token}"}
        params = {"email": self.slack_email}

        response = requests.get(
            "https://slack.com/api/users.lookupByEmail",
            headers=headers,
            params=params
        )
        return response.json()["user"]["id"]

    def _open_slack_conversation(self, user_id: str) -> str:
        """Open a Slack conversation with the user."""
        headers = {"Authorization": f"Bearer {self.slack_token}"}
        data = {"users": user_id}

        response = requests.post(
            "https://slack.com/api/conversations.open",
            headers=headers,
            json=data
        )
        return response.json()["channel"]["id"]

    def _post_slack_message(self, channel_id: str, message: str) -> None:
        """Post a message to a Slack channel."""
        headers = {"Authorization": f"Bearer {self.slack_token}"}
        data = {"channel": channel_id, "text": message}

        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json=data
        )


class ActivityDataProcessor:
    """Processes litter robot activity data."""

    ACTIVITY_MAPPING = {
        "LitterBoxStatus.CAT_SENSOR_INTERRUPTED": "Cycle Interrupted",
        "LitterBoxStatus.CAT_DETECTED": "Cat Detected",
        "LitterBoxStatus.CLEAN_CYCLE": "Clean Cycle In Progress",
        "LitterBoxStatus.CLEAN_CYCLE_COMPLETE": "Clean Cycle Complete",
    }

    def process_activities(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process raw activity data into structured format."""
        # Map activities to readable names
        df["Activity"] = df["Activity"].map(self.ACTIVITY_MAPPING).fillna(df["Activity"])

        # Extract weight and clean cycle data
        self._extract_weight_data(df)
        self._extract_clean_cycle_data(df)

        # Sort by datetime
        df.sort_values("DateTime", inplace=True)

        return df

    def _extract_weight_data(self, df: pd.DataFrame) -> None:
        """Extract weight values from activity strings."""
        self._extract_and_update_values(
            df,
            r"Pet Weight Recorded: (\d+\.?\d*) lbs",
            "Weight Recorded",
            float
        )

    def _extract_clean_cycle_data(self, df: pd.DataFrame) -> None:
        """Extract clean cycle counts from activity strings."""
        self._extract_and_update_values(
            df,
            r"Clean Cycles: (\d+)",
            "Clean Cycles",
            int
        )

    def _extract_and_update_values(
        self, df: pd.DataFrame, pattern: str, activity_name: str, dtype: type
    ) -> None:
        """Extract values from activity strings and update DataFrame."""
        values = df["Activity"].str.extract(pattern)[0]
        mask = values.notna()
        df.loc[mask, "Activity"] = activity_name
        df.loc[mask, "Value"] = values[mask].astype(dtype)


class ActivityAnalyzer:
    """Analyzes litter robot activity patterns."""

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def get_usage_count(self) -> int:
        """Get the number of clean cycles (visits) for the day."""
        return int((self.df["Activity"] == "Clean Cycle In Progress").sum())

    def get_average_weight(self) -> Optional[float]:
        """Calculate average weight from valid measurements."""
        weight_data = self.df[self.df["Activity"] == "Weight Recorded"]["Value"].dropna()

        if len(weight_data) == 0:
            return None

        # Filter valid weights
        valid_weights = weight_data[
            (weight_data >= Config.MIN_VALID_WEIGHT) &
            (weight_data <= Config.MAX_VALID_WEIGHT)
        ]

        if len(valid_weights) == 0:
            return None

        return valid_weights.mean()

    def has_cycle_delays(self) -> bool:
        """Check if there are delays > CYCLE_DELAY + USAGE_DURATION between Weight Recorded and Clean Cycle."""
        weight_groups = self._get_consecutive_weight_groups()
        threshold_minutes = Config.CYCLE_DELAY + Config.USAGE_DURATION

        for weight_group in weight_groups:
            if self._check_delay_after_weight_group(weight_group, threshold_minutes):
                return True

        return False

    def has_consecutive_weights(self) -> bool:
        """Check if there are CONSECUTIVE_WEIGHT_THRESHOLD or more consecutive Weight Recorded events."""
        weight_groups = self._get_consecutive_weight_groups()

        for weight_group in weight_groups:
            if len(weight_group) >= Config.CONSECUTIVE_WEIGHT_THRESHOLD:
                return True

        return False

    def _get_consecutive_weight_groups(self) -> List[List[pd.Series]]:
        """Group consecutive Weight Recorded events."""
        df_sorted = self.df.sort_values('DateTime').reset_index(drop=True)
        weight_recorded = df_sorted[df_sorted['Activity'] == 'Weight Recorded']

        weight_groups = []
        current_group = []

        for _, weight_row in weight_recorded.iterrows():
            if self._should_start_new_group(current_group, weight_row, df_sorted):
                if current_group:
                    weight_groups.append(current_group)
                current_group = [weight_row]
            else:
                current_group.append(weight_row)

        if current_group:
            weight_groups.append(current_group)

        return weight_groups

    def _should_start_new_group(self, current_group: List[pd.Series],
                                weight_row: pd.Series,
                                df_sorted: pd.DataFrame) -> bool:
        """Determine if a new weight group should be started."""
        if not current_group:
            return False

        last_weight_time = current_group[-1]['DateTime']
        weight_time = weight_row['DateTime']

        activities_between = df_sorted[
            (df_sorted['DateTime'] > last_weight_time) &
            (df_sorted['DateTime'] < weight_time) &
            (df_sorted['Activity'] != 'Weight Recorded')
        ]

        return len(activities_between) > 0

    def _check_delay_after_weight_group(self, weight_group: List[pd.Series],
                                        threshold_minutes: int) -> bool:
        """Check if there's a delay after a weight group to the next clean cycle."""
        last_weight = weight_group[-1]
        weight_time = last_weight['DateTime']

        df_sorted = self.df.sort_values('DateTime')
        subsequent_clean = df_sorted[
            (df_sorted['DateTime'] > weight_time) &
            (df_sorted['Activity'] == 'Clean Cycle In Progress')
        ]

        if len(subsequent_clean) == 0:
            return False

        next_clean_time = subsequent_clean['DateTime'].iloc[0]
        time_diff = next_clean_time - weight_time

        return time_diff > timedelta(minutes=threshold_minutes)


class AlertGenerator:
    """Generates alert messages based on analysis results."""

    def generate_alerts(self, waste_percent: int, usage_count: int,
                        avg_weight: Optional[float], has_delays: bool,
                        has_consecutive: bool) -> List[str]:
        """Generate all applicable alert messages."""
        alerts = []

        # Waste level alert
        if waste_percent >= Config.WASTE_ALERT_THRESHOLD:
            alerts.append(
                f"Waste basket is {waste_percent}% full. Please change ASAP."
            )

        # Usage count alert
        if usage_count >= Config.HIGH_USAGE_THRESHOLD or usage_count <= Config.LOW_USAGE_THRESHOLD:
            alerts.append(
                f":poop: Cats used bathroom {usage_count} times yesterday. Please investigate."
            )

        # Weight alert
        if avg_weight is not None:
            if avg_weight <= Config.MIN_HEALTHY_WEIGHT or avg_weight >= Config.MAX_HEALTHY_WEIGHT:
                alerts.append(
                    f"Avg Weight yesterday = {avg_weight:.1f} lbs. Please investigate."
                )

        # Cycle delay alert
        if has_delays:
            alerts.append(
                f">{Config.USAGE_DURATION} min usage duration yesterday. Please investigate."
            )

        # Consecutive weight recordings alert
        if has_consecutive:
            alerts.append(
                f"Cat(s) entered {Config.CONSECUTIVE_WEIGHT_THRESHOLD}+ times before cycling yesterday. Please investigate."
            )

        return alerts


class LitterRobotMonitor:
    """Monitor litter robot activity and send alerts for anomalies."""

    def __init__(self):
        """Initialize the monitor with environment variables."""
        self.credentials = self._load_credentials()
        self.notification_service = NotificationService(
            self.credentials['email'],
            self.credentials['gmail_password'],
            self.credentials['slack_token'],
            self.credentials['slack_email']
        )
        self.data_processor = ActivityDataProcessor()
        self.alert_generator = AlertGenerator()

    def _load_credentials(self) -> Dict[str, str]:
        """Load credentials from environment variables."""
        return {
            'email': os.environ["LITTER_ROBOT_USERNAME"],
            'gmail_password': os.environ["GMAIL_PASSWORD"],
            'litter_robot_password': os.environ["LITTER_ROBOT_PASSWORD"],
            'slack_token': os.environ["SLACK_BOT_TOKEN"],
            'slack_email': os.environ["SLACK_EMAIL"]
        }

    async def run(self) -> None:
        """Main monitoring routine."""
        try:
            # TEST MODE: Read from CSV instead of API
            # activities, waste_percent = await self._fetch_litter_robot_data()
            df, waste_percent = self._load_test_data_from_csv()

            # Process activity data
            # df = self._create_dataframe(activities)
            df = self._filter_yesterday_data(df)

            # Check for low usage
            if self._is_low_usage(df):
                self._send_low_usage_alert()
                sys.exit(1)

            # Process and analyze activities
            df = self.data_processor.process_activities(df)
            self._save_to_csv(df)

            # Analyze patterns
            analyzer = ActivityAnalyzer(df)
            analysis_results = self._analyze_activities(analyzer)

            # Generate and send alerts
            self._send_alerts_if_needed(waste_percent, analysis_results)

        except Exception as e:
            self._handle_api_error(e)
            sys.exit(1)

    def _load_test_data_from_csv(self) -> Tuple[pd.DataFrame, int]:
        """Load test data from CSV file instead of API."""
        # Read existing CSV
        df = pd.read_csv(Config.CSV_OUTPUT_FILE)
        df["DateTime"] = pd.to_datetime(df["DateTime"], utc=True).dt.tz_convert(Config.TIMEZONE)
        
        # Set a high waste percentage to trigger waste alert
        waste_percent = 80  # This will trigger the waste alert (>= 75%)
        
        return df, waste_percent

    # COMMENTED OUT - Original API method
    # async def _fetch_litter_robot_data(self) -> Tuple[List[Any], int]:
    #     """Fetch activity history and waste level from the litter robot API."""
    #     account = Account()
    #     await account.connect(
    #         username=self.credentials['email'],
    #         password=self.credentials['litter_robot_password'],
    #         load_robots=True,
    #     )

    #     activities = await account.robots[0].get_activity_history(
    #         limit=Config.ACTIVITY_HISTORY_LIMIT
    #     )
    #     waste_percent = account.robots[0].waste_drawer_level

    #     await account.disconnect()

    #     return activities, waste_percent

    def _create_dataframe(self, activities: List[Any]) -> pd.DataFrame:
        """Create a DataFrame from activity data."""
        df = pd.DataFrame({
            "Timestamp": [act.timestamp for act in activities],
            "Activity": [str(act.action) for act in activities],
        })
        df["DateTime"] = df["Timestamp"].dt.tz_convert(Config.TIMEZONE)
        df["Value"] = None  # Initialize Value column
        return df

    def _filter_yesterday_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter DataFrame to only include yesterday's data."""
        yesterday = pd.Timestamp.now(tz=Config.TIMEZONE).date() - pd.Timedelta(days=1)
        return df[df["DateTime"].dt.date == yesterday][["DateTime", "Activity", "Value"]]

    def _is_low_usage(self, df: pd.DataFrame) -> bool:
        """Check if usage is critically low."""
        return len(df) <= 1

    def _send_low_usage_alert(self) -> None:
        """Send alert for critically low usage."""
        self.notification_service.send_email(
            "LR4 Data Warning",
            "Bruno & Murano used the litter box <=1 time yesterday!"
        )

    def _save_to_csv(self, df: pd.DataFrame) -> None:
        """Append processed data to CSV file."""
        df.to_csv(Config.CSV_OUTPUT_FILE, mode="a", header=False, index=False)

    def _analyze_activities(self, analyzer: ActivityAnalyzer) -> Dict[str, Any]:
        """Perform all activity analyses."""
        return {
            'usage_count': analyzer.get_usage_count(),
            'avg_weight': analyzer.get_average_weight(),
            'has_delays': analyzer.has_cycle_delays(),
            'has_consecutive': analyzer.has_consecutive_weights()
        }

    def _send_alerts_if_needed(self, waste_percent: int,
                               analysis_results: Dict[str, Any]) -> None:
        """Generate and send alerts if any issues are detected."""
        alerts = self.alert_generator.generate_alerts(
            waste_percent,
            analysis_results['usage_count'],
            analysis_results['avg_weight'],
            analysis_results['has_delays'],
            analysis_results['has_consecutive']
        )

        if alerts:
            self.notification_service.send_slack_message("\n".join(alerts))

    def _handle_api_error(self, error: Exception) -> None:
        """Handle API errors by sending an email notification."""
        self.notification_service.send_email(
            "LR4 Data Warning",
            f"API returned an error: {error}"
        )


async def main():
    """Entry point for the litter robot monitor."""
    monitor = LitterRobotMonitor()
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())


# #!/usr/bin/env python
# # coding: utf-8

# import asyncio
# import os
# import smtplib
# import sys
# from datetime import timedelta
# from email.mime.text import MIMEText
# from typing import List, Dict, Any, Optional, Tuple

# import pandas as pd
# import requests
# from pylitterbot import Account


# class Config:
#     """Configuration constants for the litter robot monitor."""

#     # Activity thresholds
#     LOW_USAGE_THRESHOLD = 4
#     HIGH_USAGE_THRESHOLD = 9

#     # Weight thresholds (in pounds)
#     MIN_HEALTHY_WEIGHT = 8.5
#     MAX_HEALTHY_WEIGHT = 9.1
#     MIN_VALID_WEIGHT = 7.5
#     MAX_VALID_WEIGHT = 9.5

#     # Waste level threshold (percentage)
#     WASTE_ALERT_THRESHOLD = 75

#     # API limits
#     ACTIVITY_HISTORY_LIMIT = 300

#     # Email configuration
#     SMTP_SERVER = "smtp.gmail.com"
#     SMTP_PORT = 587
#     SMTP_TIMEOUT = 30

#     # Timezone
#     TIMEZONE = "America/New_York"

#     # File paths
#     CSV_OUTPUT_FILE = "master_lr4_practice.csv"

#     # Cycle timing thresholds
#     CYCLE_DELAY = 7  # minutes
#     USAGE_DURATION = 5  # minutes
#     CONSECUTIVE_WEIGHT_THRESHOLD = 3  # number of consecutive weight recordings


# class NotificationService:
#     """Handles email and Slack notifications."""

#     def __init__(self, sender_email: str, sender_password: str,
#                  slack_token: str, slack_email: str):
#         self.sender_email = sender_email
#         self.sender_password = sender_password
#         self.slack_token = slack_token
#         self.slack_email = slack_email

#     def send_email(self, subject: str, message: str) -> None:
#         """Send email notification."""
#         msg = MIMEText(message)
#         msg["Subject"] = subject
#         msg["From"] = self.sender_email
#         msg["To"] = self.sender_email

#         with smtplib.SMTP(
#             Config.SMTP_SERVER, Config.SMTP_PORT, timeout=Config.SMTP_TIMEOUT
#         ) as server:
#             server.starttls()
#             server.login(self.sender_email, self.sender_password)
#             server.sendmail(self.sender_email, self.sender_email, msg.as_string())

#     def send_slack_message(self, message: str) -> None:
#         """Send message to Slack."""
#         user_id = self._get_slack_user_id()
#         channel_id = self._open_slack_conversation(user_id)
#         self._post_slack_message(channel_id, message)

#     def _get_slack_user_id(self) -> str:
#         """Get Slack user ID from email."""
#         headers = {"Authorization": f"Bearer {self.slack_token}"}
#         params = {"email": self.slack_email}

#         response = requests.get(
#             "https://slack.com/api/users.lookupByEmail",
#             headers=headers,
#             params=params
#         )
#         return response.json()["user"]["id"]

#     def _open_slack_conversation(self, user_id: str) -> str:
#         """Open a Slack conversation with the user."""
#         headers = {"Authorization": f"Bearer {self.slack_token}"}
#         data = {"users": user_id}

#         response = requests.post(
#             "https://slack.com/api/conversations.open",
#             headers=headers,
#             json=data
#         )
#         return response.json()["channel"]["id"]

#     def _post_slack_message(self, channel_id: str, message: str) -> None:
#         """Post a message to a Slack channel."""
#         headers = {"Authorization": f"Bearer {self.slack_token}"}
#         data = {"channel": channel_id, "text": message}

#         requests.post(
#             "https://slack.com/api/chat.postMessage",
#             headers=headers,
#             json=data
#         )


# class ActivityDataProcessor:
#     """Processes litter robot activity data."""

#     ACTIVITY_MAPPING = {
#         "LitterBoxStatus.CAT_SENSOR_INTERRUPTED": "Cycle Interrupted",
#         "LitterBoxStatus.CAT_DETECTED": "Cat Detected",
#         "LitterBoxStatus.CLEAN_CYCLE": "Clean Cycle In Progress",
#         "LitterBoxStatus.CLEAN_CYCLE_COMPLETE": "Clean Cycle Complete",
#     }

#     def process_activities(self, df: pd.DataFrame) -> pd.DataFrame:
#         """Process raw activity data into structured format."""
#         # Map activities to readable names
#         df["Activity"] = df["Activity"].map(self.ACTIVITY_MAPPING).fillna(df["Activity"])

#         # Extract weight and clean cycle data
#         self._extract_weight_data(df)
#         self._extract_clean_cycle_data(df)

#         # Sort by datetime
#         df.sort_values("DateTime", inplace=True)

#         return df

#     def _extract_weight_data(self, df: pd.DataFrame) -> None:
#         """Extract weight values from activity strings."""
#         self._extract_and_update_values(
#             df,
#             r"Pet Weight Recorded: (\d+\.?\d*) lbs",
#             "Weight Recorded",
#             float
#         )

#     def _extract_clean_cycle_data(self, df: pd.DataFrame) -> None:
#         """Extract clean cycle counts from activity strings."""
#         self._extract_and_update_values(
#             df,
#             r"Clean Cycles: (\d+)",
#             "Clean Cycles",
#             int
#         )

#     def _extract_and_update_values(
#         self, df: pd.DataFrame, pattern: str, activity_name: str, dtype: type
#     ) -> None:
#         """Extract values from activity strings and update DataFrame."""
#         values = df["Activity"].str.extract(pattern)[0]
#         mask = values.notna()
#         df.loc[mask, "Activity"] = activity_name
#         df.loc[mask, "Value"] = values[mask].astype(dtype)


# class ActivityAnalyzer:
#     """Analyzes litter robot activity patterns."""

#     def __init__(self, df: pd.DataFrame):
#         self.df = df

#     def get_usage_count(self) -> int:
#         """Get the number of clean cycles (visits) for the day."""
#         return int((self.df["Activity"] == "Clean Cycle In Progress").sum())

#     def get_average_weight(self) -> Optional[float]:
#         """Calculate average weight from valid measurements."""
#         weight_data = self.df[self.df["Activity"] == "Weight Recorded"]["Value"].dropna()

#         if len(weight_data) == 0:
#             return None

#         # Filter valid weights
#         valid_weights = weight_data[
#             (weight_data >= Config.MIN_VALID_WEIGHT) &
#             (weight_data <= Config.MAX_VALID_WEIGHT)
#         ]

#         if len(valid_weights) == 0:
#             return None

#         return valid_weights.mean()

#     def has_cycle_delays(self) -> bool:
#         """Check if there are delays > CYCLE_DELAY + USAGE_DURATION between Weight Recorded and Clean Cycle."""
#         weight_groups = self._get_consecutive_weight_groups()
#         threshold_minutes = Config.CYCLE_DELAY + Config.USAGE_DURATION

#         for weight_group in weight_groups:
#             if self._check_delay_after_weight_group(weight_group, threshold_minutes):
#                 return True

#         return False

#     def has_consecutive_weights(self) -> bool:
#         """Check if there are CONSECUTIVE_WEIGHT_THRESHOLD or more consecutive Weight Recorded events."""
#         weight_groups = self._get_consecutive_weight_groups()

#         for weight_group in weight_groups:
#             if len(weight_group) >= Config.CONSECUTIVE_WEIGHT_THRESHOLD:
#                 return True

#         return False

#     def _get_consecutive_weight_groups(self) -> List[List[pd.Series]]:
#         """Group consecutive Weight Recorded events."""
#         df_sorted = self.df.sort_values('DateTime').reset_index(drop=True)
#         weight_recorded = df_sorted[df_sorted['Activity'] == 'Weight Recorded']

#         weight_groups = []
#         current_group = []

#         for _, weight_row in weight_recorded.iterrows():
#             if self._should_start_new_group(current_group, weight_row, df_sorted):
#                 if current_group:
#                     weight_groups.append(current_group)
#                 current_group = [weight_row]
#             else:
#                 current_group.append(weight_row)

#         if current_group:
#             weight_groups.append(current_group)

#         return weight_groups

#     def _should_start_new_group(self, current_group: List[pd.Series],
#                                 weight_row: pd.Series,
#                                 df_sorted: pd.DataFrame) -> bool:
#         """Determine if a new weight group should be started."""
#         if not current_group:
#             return False

#         last_weight_time = current_group[-1]['DateTime']
#         weight_time = weight_row['DateTime']

#         activities_between = df_sorted[
#             (df_sorted['DateTime'] > last_weight_time) &
#             (df_sorted['DateTime'] < weight_time) &
#             (df_sorted['Activity'] != 'Weight Recorded')
#         ]

#         return len(activities_between) > 0

#     def _check_delay_after_weight_group(self, weight_group: List[pd.Series],
#                                         threshold_minutes: int) -> bool:
#         """Check if there's a delay after a weight group to the next clean cycle."""
#         last_weight = weight_group[-1]
#         weight_time = last_weight['DateTime']

#         df_sorted = self.df.sort_values('DateTime')
#         subsequent_clean = df_sorted[
#             (df_sorted['DateTime'] > weight_time) &
#             (df_sorted['Activity'] == 'Clean Cycle In Progress')
#         ]

#         if len(subsequent_clean) == 0:
#             return False

#         next_clean_time = subsequent_clean['DateTime'].iloc[0]
#         time_diff = next_clean_time - weight_time

#         return time_diff > timedelta(minutes=threshold_minutes)


# class AlertGenerator:
#     """Generates alert messages based on analysis results."""

#     def generate_alerts(self, waste_percent: int, usage_count: int,
#                         avg_weight: Optional[float], has_delays: bool,
#                         has_consecutive: bool) -> List[str]:
#         """Generate all applicable alert messages."""
#         alerts = []

#         # Waste level alert
#         if waste_percent >= Config.WASTE_ALERT_THRESHOLD:
#             alerts.append(
#                 f"Waste basket is {waste_percent}% full. Please change ASAP."
#             )

#         # Usage count alert
#         if usage_count >= Config.HIGH_USAGE_THRESHOLD or usage_count <= Config.LOW_USAGE_THRESHOLD:
#             alerts.append(
#                 f":poop: Cats used bathroom {usage_count} times yesterday. Please investigate."
#             )

#         # Weight alert
#         if avg_weight is not None:
#             if avg_weight <= Config.MIN_HEALTHY_WEIGHT or avg_weight >= Config.MAX_HEALTHY_WEIGHT:
#                 alerts.append(
#                     f"Avg Weight yesterday = {avg_weight:.1f} lbs. Please investigate."
#                 )

#         # Cycle delay alert
#         if has_delays:
#             alerts.append(
#                 f">{Config.USAGE_DURATION} min usage duration yesterday. Please investigate."
#             )

#         # Consecutive weight recordings alert
#         if has_consecutive:
#             alerts.append(
#                 f"Cat(s) entered {Config.CONSECUTIVE_WEIGHT_THRESHOLD}+ times before cycling yesterday. Please investigate."
#             )

#         return alerts


# class LitterRobotMonitor:
#     """Monitor litter robot activity and send alerts for anomalies."""

#     def __init__(self):
#         """Initialize the monitor with environment variables."""
#         self.credentials = self._load_credentials()
#         self.notification_service = NotificationService(
#             self.credentials['email'],
#             self.credentials['gmail_password'],
#             self.credentials['slack_token'],
#             self.credentials['slack_email']
#         )
#         self.data_processor = ActivityDataProcessor()
#         self.alert_generator = AlertGenerator()

#     def _load_credentials(self) -> Dict[str, str]:
#         """Load credentials from environment variables."""
#         return {
#             'email': os.environ["LITTER_ROBOT_USERNAME"],
#             'gmail_password': os.environ["GMAIL_PASSWORD"],
#             'litter_robot_password': os.environ["LITTER_ROBOT_PASSWORD"],
#             'slack_token': os.environ["SLACK_BOT_TOKEN"],
#             'slack_email': os.environ["SLACK_EMAIL"]
#         }

#     async def run(self) -> None:
#         """Main monitoring routine."""
#         try:
#             # Fetch data from API
#             activities, waste_percent = await self._fetch_litter_robot_data()

#             # Process activity data
#             df = self._create_dataframe(activities)
#             df = self._filter_yesterday_data(df)

#             # Check for low usage
#             if self._is_low_usage(df):
#                 self._send_low_usage_alert()
#                 sys.exit(1)

#             # Process and analyze activities
#             df = self.data_processor.process_activities(df)
#             self._save_to_csv(df)

#             # Analyze patterns
#             analyzer = ActivityAnalyzer(df)
#             analysis_results = self._analyze_activities(analyzer)

#             # Generate and send alerts
#             self._send_alerts_if_needed(waste_percent, analysis_results)

#         except Exception as e:
#             self._handle_api_error(e)
#             sys.exit(1)

#     async def _fetch_litter_robot_data(self) -> Tuple[List[Any], int]:
#         """Fetch activity history and waste level from the litter robot API."""
#         account = Account()
#         await account.connect(
#             username=self.credentials['email'],
#             password=self.credentials['litter_robot_password'],
#             load_robots=True,
#         )

#         activities = await account.robots[0].get_activity_history(
#             limit=Config.ACTIVITY_HISTORY_LIMIT
#         )
#         waste_percent = account.robots[0].waste_drawer_level

#         await account.disconnect()

#         return activities, waste_percent

#     def _create_dataframe(self, activities: List[Any]) -> pd.DataFrame:
#         """Create a DataFrame from activity data."""
#         df = pd.DataFrame({
#             "Timestamp": [act.timestamp for act in activities],
#             "Activity": [str(act.action) for act in activities],
#         })
#         df["DateTime"] = df["Timestamp"].dt.tz_convert(Config.TIMEZONE)
#         df["Value"] = None  # Initialize Value column
#         return df

#     def _filter_yesterday_data(self, df: pd.DataFrame) -> pd.DataFrame:
#         """Filter DataFrame to only include yesterday's data."""
#         yesterday = pd.Timestamp.now(tz=Config.TIMEZONE).date() - pd.Timedelta(days=1)
#         return df[df["DateTime"].dt.date == yesterday][["DateTime", "Activity", "Value"]]

#     def _is_low_usage(self, df: pd.DataFrame) -> bool:
#         """Check if usage is critically low."""
#         return len(df) <= 1

#     def _send_low_usage_alert(self) -> None:
#         """Send alert for critically low usage."""
#         self.notification_service.send_email(
#             "LR4 Data Warning",
#             "Bruno & Murano used the litter box <=1 time yesterday!"
#         )

#     def _save_to_csv(self, df: pd.DataFrame) -> None:
#         """Append processed data to CSV file."""
#         df.to_csv(Config.CSV_OUTPUT_FILE, mode="a", header=False, index=False)

#     def _analyze_activities(self, analyzer: ActivityAnalyzer) -> Dict[str, Any]:
#         """Perform all activity analyses."""
#         return {
#             'usage_count': analyzer.get_usage_count(),
#             'avg_weight': analyzer.get_average_weight(),
#             'has_delays': analyzer.has_cycle_delays(),
#             'has_consecutive': analyzer.has_consecutive_weights()
#         }

#     def _send_alerts_if_needed(self, waste_percent: int,
#                                analysis_results: Dict[str, Any]) -> None:
#         """Generate and send alerts if any issues are detected."""
#         alerts = self.alert_generator.generate_alerts(
#             waste_percent,
#             analysis_results['usage_count'],
#             analysis_results['avg_weight'],
#             analysis_results['has_delays'],
#             analysis_results['has_consecutive']
#         )

#         if alerts:
#             self.notification_service.send_slack_message("\n".join(alerts))

#     def _handle_api_error(self, error: Exception) -> None:
#         """Handle API errors by sending an email notification."""
#         self.notification_service.send_email(
#             "LR4 Data Warning",
#             f"API returned an error: {error}"
#         )


# async def main():
#     """Entry point for the litter robot monitor."""
#     monitor = LitterRobotMonitor()
#     await monitor.run()


# if __name__ == "__main__":
#     asyncio.run(main())
