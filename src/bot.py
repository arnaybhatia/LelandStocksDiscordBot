import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import os
import json
import pandas as pd
from pytz import timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up Discord bot intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# Initialize bot instance with command prefix
bot = commands.Bot(command_prefix="$", intents=intents)


def get_user_info(df, username):
    """
    Retrieve and format information for a specific user from the DataFrame.
    """
    df["Money In Account"] = pd.to_numeric(df["Money In Account"], errors="coerce")
    user_row = df[df["Account Name"] == username]
    if user_row.empty:
        return None
    user_data = user_row.iloc[0]
    user_name = user_data["Account Name"]
    user_money = user_data["Money In Account"]
    user_stocks = user_data["Stocks Invested In"]
    formatted_holdings = "\n".join(
        [f"{stock[0]}: {stock[1]} ({stock[2]})" for stock in user_stocks]
    )
    return user_name, user_money, formatted_holdings


def get_latest_in_time_leaderboard():
    """
    Get the most recent leaderboard file from the in_time directory.
    """
    in_time_dir = "./backend/leaderboards/in_time"
    files = [f for f in os.listdir(in_time_dir) if f.endswith(".json")]
    if not files:
        return None
    latest_file = max(
        files, key=lambda x: os.path.getctime(os.path.join(in_time_dir, x))
    )
    return os.path.join(in_time_dir, latest_file)


def get_pst_time():
    """Helper function to get current time in PST"""
    return datetime.datetime.now(timezone("America/Los_Angeles"))


async def compare_stock_changes(channel):
    """
    Compare current leaderboard with snapshot to detect stock changes, and send updates to the Discord channel as embeds.
    """
    try:
        # Load the snapshot file
        snapshot_path = "./backend/leaderboards/snapshots/leaderboard-snapshot.json"
        if not os.path.exists(snapshot_path):
            # If snapshot doesn't exist, create it and return
            with open("./backend/leaderboards/leaderboard-latest.json", "r") as f:
                current_data = json.load(f)
            with open(snapshot_path, "w") as f:
                json.dump(current_data, f)
            return

        # Load both snapshot and current data
        with open(snapshot_path, "r") as f:
            previous_data = json.load(f)
        with open("./backend/leaderboards/leaderboard-latest.json", "r") as f:
            current_data = json.load(f)
        # Compare holdings for each user
        for username in current_data:
            if username not in previous_data:
                continue

            # Get current and previous stock symbols
            current_stocks = set(stock[0] for stock in current_data[username][2])
            previous_stocks = set(stock[0] for stock in previous_data[username][2])

            # Find new and removed stocks
            new_stocks = current_stocks - previous_stocks
            removed_stocks = previous_stocks - current_stocks

            if new_stocks or removed_stocks:
                description = ""
                for stock in new_stocks:
                    description += f"+ Bought {stock}\n"
                for stock in removed_stocks:
                    description += f"- Sold {stock}\n"

                embed = discord.Embed(
                    colour=discord.Colour.green(),
                    title=f"Stock Changes for {username}",
                    description=description,
                    timestamp=get_pst_time(),
                )
                await channel.send(embed=embed)

        # Update the snapshot with current data after comparison
        with open(snapshot_path, "w") as f:
            json.dump(current_data, f)

    except Exception as e:
        await channel.send(f"Error comparing stock changes: {str(e)}")
        import traceback

        traceback.print_exc()


# Load usernames from file
with open("./backend/portfolios/usernames.txt", "r") as f:
    usernames_list = [line.strip() for line in f.readlines()]


class UserInfo(commands.Cog):
    """
    Cog to handle user information related commands.
    """

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="Get user information")
    @app_commands.describe(username="Select a username")
    async def userinfo(self, interaction: discord.Interaction, username: str):
        """
        Respond to the /userinfo command with the user's information.
        """
        await interaction.response.defer()
        try:
            with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
                data = json.load(file)
            df = pd.DataFrame.from_dict(data, orient="index")
            df.reset_index(inplace=True)
            df.columns = [
                "Account Name",
                "Money In Account",
                "Investopedia Link",
                "Stocks Invested In",
            ]

            user_info = get_user_info(df, username)
            if user_info is None:
                await interaction.followup.send(f"User '{username}' not found.")
                return

            user_name, user_money, user_holdings = user_info
            embed = discord.Embed(
                colour=discord.Colour.blue(),
                title=f"Information for {user_name}",
                description=(
                    f"**Current Money:** {user_money}\n\n"
                    f"**Current Holdings:**\n{user_holdings}"
                ),
                timestamp=get_pst_time(),
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error fetching user info: {str(e)}")

    @userinfo.autocomplete("username")
    async def username_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        """
        Provide autocomplete suggestions for usernames based on current input.
        """
        return [
            app_commands.Choice(name=username, value=username)
            for username in usernames_list
            if current.lower() in username.lower()
        ][:25]


async def setup(bot):
    """
    Add the UserInfo cog to the bot.
    """
    await bot.add_cog(UserInfo(bot))


async def setup_hook():
    """
    Run setup when the bot is ready.
    """
    await setup(bot)


bot.setup_hook = setup_hook


@bot.tree.command(name="leaderboard", description="Get current leaderboard")
@app_commands.describe(count="Number of top users to display (default: 1)")
async def leaderboard(interaction: discord.Interaction, count: int = 1):
    """
    Respond to the /leaderboard command with the top N users' info.
    """
    await interaction.response.defer()
    try:
        with open("./backend/leaderboards/leaderboard-latest.json", "r") as file:
            data = json.load(file)
        df = pd.DataFrame.from_dict(data, orient="index")
        df.reset_index(inplace=True)
        df.columns = [
            "Account Name",
            "Money In Account",
            "Investopedia Link",
            "Stocks Invested In",
        ]
        df.sort_values(by="Money In Account", ascending=False, inplace=True)

        # Limit count to be between 1 and 10
        count = max(1, min(count, 10))

        description = ""
        for i in range(min(count, len(df))):
            user_name, user_money, user_stocks = get_user_info(
                df, df.iloc[i]["Account Name"]
            )
            description += f"**#{i+1} - {user_name}**\n"
            description += f"Money: {user_money}\n"
            description += f"Holdings:\n{user_stocks}\n\n"

        embed = discord.Embed(
            colour=discord.Colour.dark_red(),
            title="Current Leaderboard",
            description=description,
            timestamp=get_pst_time(),
        )
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"Error fetching leaderboard: {str(e)}")


@tasks.loop(minutes=1)
async def send_leaderboard():
    """
    Periodically send the leaderboard update to the Discord channels during trading hours.
    """
    now = datetime.datetime.now(timezone("US/Eastern"))
    if now.weekday() < 5:
        start_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        end_time = now.replace(hour=16, minute=15, second=0, microsecond=0)
        if start_time <= now <= end_time:
            try:
                with open(
                    "./backend/leaderboards/leaderboard-latest.json", "r"
                ) as file:
                    data = json.load(file)
                df = pd.DataFrame.from_dict(data, orient="index")
                df.reset_index(inplace=True)
                df.columns = [
                    "Account Name",
                    "Money In Account",
                    "Investopedia Link",
                    "Stocks Invested In",
                ]
                df.sort_values(by="Money In Account", ascending=False, inplace=True)

                top_ranked_name, top_ranked_money, top_ranked_stocks = get_user_info(
                    df, df.iloc[0]["Account Name"]
                )
                leaderboard_channel_id = int(
                    os.environ.get("DISCORD_CHANNEL_ID_Leaderboard")
                )
                stocks_channel_id = int(os.environ.get("DISCORD_CHANNEL_ID_Stocks"))
                leaderboard_channel = bot.get_channel(leaderboard_channel_id)
                stocks_channel = bot.get_channel(stocks_channel_id)

                if leaderboard_channel:
                    embed = discord.Embed(
                        colour=discord.Colour.dark_red(),
                        title="Leaderboard Update!",
                        description=(
                            f"**Top Ranked Person:** {top_ranked_name}\n\n"
                            f"**Current Money:** {top_ranked_money}\n\n"
                            f"**Current Holdings:**\n{top_ranked_stocks}"
                        ),
                        timestamp=get_pst_time(),
                    )
                    await leaderboard_channel.send(embed=embed)

                if stocks_channel:
                    await compare_stock_changes(stocks_channel)

            except Exception as e:
                print(f"Error in send_leaderboard: {str(e)}")


def calculate_daily_performance(previous_data, current_data):
    """Calculate performance metrics for all users over the day"""
    performance = []
    total_trades = 0
    biggest_gain = {"username": "", "amount": 0, "percent": 0}
    biggest_loss = {"username": "", "amount": 0, "percent": 0}

    for username in current_data:
        if username in previous_data:
            prev_money = float(previous_data[username][0])
            curr_money = float(current_data[username][0])
            trades = set(stock[0] for stock in current_data[username][2]) ^ set(
                stock[0] for stock in previous_data[username][2]
            )
            trade_count = len(trades)
            total_trades += trade_count

            change_amount = curr_money - prev_money
            percent_change = (change_amount / prev_money) * 100

            # Track biggest single gain/loss
            if percent_change > biggest_gain["percent"]:
                biggest_gain = {
                    "username": username,
                    "amount": change_amount,
                    "percent": percent_change,
                }
            if percent_change < biggest_loss["percent"]:
                biggest_loss = {
                    "username": username,
                    "amount": change_amount,
                    "percent": percent_change,
                }

            performance.append(
                {
                    "username": username,
                    "change_amount": change_amount,
                    "change_percent": percent_change,
                    "trades": trade_count,
                }
            )

    return {
        "performance": sorted(
            performance, key=lambda x: x["change_percent"], reverse=True
        ),
        "total_trades": total_trades,
        "biggest_gain": biggest_gain,
        "biggest_loss": biggest_loss,
        "most_active": sorted(performance, key=lambda x: x["trades"], reverse=True)[:3],
    }


async def create_morning_snapshot():
    """Create a snapshot of the leaderboard at market open"""
    try:
        morning_snapshot_path = "./backend/leaderboards/snapshots/morning-snapshot.json"
        with open("./backend/leaderboards/leaderboard-latest.json", "r") as f:
            current_data = json.load(f)
        with open(morning_snapshot_path, "w") as f:
            json.dump(current_data, f)
    except Exception as e:
        print(f"Error creating morning snapshot: {str(e)}")


@tasks.loop(time=datetime.time(hour=9, minute=30, tzinfo=timezone("US/Eastern")))
async def start_of_day():
    """Create snapshot at market open"""
    now = datetime.datetime.now(timezone("US/Eastern"))
    if now.weekday() < 5:  # Only on weekdays
        await create_morning_snapshot()


@tasks.loop(time=datetime.time(hour=16, minute=0, tzinfo=timezone("US/Eastern")))
async def send_daily_summary():
    """Send daily summary comparing start of day to end of day"""
    now = datetime.datetime.now(timezone("US/Eastern"))
    if now.weekday() < 5:  # Only on weekdays
        try:
            # Load morning snapshot instead of previous day's snapshot
            morning_snapshot_path = (
                "./backend/leaderboards/snapshots/morning-snapshot.json"
            )
            if not os.path.exists(morning_snapshot_path):
                print("No morning snapshot found")
                return

            with open(morning_snapshot_path, "r") as f:
                morning_data = json.load(f)

            # Load end of day data
            with open("./backend/leaderboards/leaderboard-latest.json", "r") as f:
                current_data = json.load(f)

            # Calculate performance using morning data
            stats = calculate_daily_performance(morning_data, current_data)

            if stats["performance"]:
                embed = discord.Embed(
                    colour=discord.Colour.gold(),
                    title="📊 End of Day Trading Summary",
                    description=f"Market Close Summary for {now.strftime('%A, %B %d, %Y')}",
                    timestamp=get_pst_time(),
                )

                # Overall stats
                embed.add_field(
                    name="📈 Market Activity",
                    value=f"Total Trades Today: {stats['total_trades']}\n",
                    inline=False,
                )

                # Top performers
                top_text = "\n".join(
                    [
                        f"**{p['username']}**: {p['change_percent']:+.2f}% (${p['change_amount']:,.2f}) - {p['trades']} trades"
                        for p in stats["performance"][:3]
                    ]
                )
                embed.add_field(name="🏆 Top Performers", value=top_text, inline=False)

                # Bottom performers
                bottom_text = "\n".join(
                    [
                        f"**{p['username']}**: {p['change_percent']:+.2f}% (${p['change_amount']:,.2f}) - {p['trades']} trades"
                        for p in stats["performance"][-3:]
                    ]
                )
                embed.add_field(
                    name="📉 Needs Improvement", value=bottom_text, inline=False
                )

                # Biggest moves
                if stats["biggest_gain"]["username"]:
                    embed.add_field(
                        name="🚀 Biggest Gain",
                        value=f"**{stats['biggest_gain']['username']}**\n{stats['biggest_gain']['percent']:+.2f}% (${stats['biggest_gain']['amount']:,.2f})",
                        inline=True,
                    )

                if stats["biggest_loss"]["username"]:
                    embed.add_field(
                        name="💥 Biggest Loss",
                        value=f"**{stats['biggest_loss']['username']}**\n{stats['biggest_loss']['percent']:+.2f}% (${stats['biggest_loss']['amount']:,.2f})",
                        inline=True,
                    )

                # Most active traders
                active_text = "\n".join(
                    [
                        f"**{p['username']}**: {p['trades']} trades"
                        for p in stats["most_active"]
                    ]
                )
                embed.add_field(
                    name="⚡ Most Active Traders", value=active_text, inline=False
                )

                channel = bot.get_channel(
                    int(os.environ.get("DISCORD_CHANNEL_ID_Leaderboard"))
                )
                if channel:
                    await channel.send(embed=embed)

        except Exception as e:
            print(f"Error in send_daily_summary: {str(e)}")


@send_daily_summary.before_loop
async def before_daily_summary():
    """Ensure bot is ready before starting the daily summary task"""
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    """
    Actions to perform when the bot is fully ready.
    """
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        # Start all scheduled tasks
        send_leaderboard.start()
        start_of_day.start()
        send_daily_summary.start()
    except Exception as e:
        print(f"Failed to sync commands: {e}")


# Run the bot with the provided token from environment variables
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
bot.run(DISCORD_BOT_TOKEN)