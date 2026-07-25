import discord
from discord.ext import commands
from discord import app_commands
import os
import aiohttp
import asyncio
import json
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta

# Configurazione Flask per il Keep-Alive (senza bloccare il deploy)
app = Flask('')

@app.route('/')
def home():
    return "Bot is online!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

GAMEMODE_EMOJIS = {
    "Sword": "⚔️", "Axe": "🪓", "UHC": "🍎", "DiaPot": "💎", "NethPot": "🔥",
    "DiaSMP": "🛡️", "SMP": "🏡", "SpearMace": "🔱", "Mace": "🔨", "Cart": "🛒", "Crystal": "🔮"
}

GAMEMODES = list(GAMEMODE_EMOJIS.keys())
STAFF_LOG_CHANNEL_NAME = "tester-logs"
DB_FILE = "database.json"

queues = {gm: [] for gm in GAMEMODES}
cooldowns = {}
last_tested_data = {}  # user_id -> {"gamemode": gm, "timestamp": iso_str, "rank": rank_name}
active_testers = {gm: None for gm in GAMEMODES}

def save_data():
    try:
        data = {
            "queues": queues,
            "cooldowns": {str(k): v.isoformat() for k, v in cooldowns.items()},
            "last_tested_data": {str(k): v for k, v in last_tested_data.items()}
        }
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving database: {e}")

def load_data():
    global queues, cooldowns, last_tested_data
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
                loaded_queues = data.get("queues", {})
                for gm in GAMEMODES:
                    if gm in loaded_queues:
                        queues[gm] = loaded_queues[gm]
                loaded_cooldowns = data.get("cooldowns", {})
                now = datetime.utcnow()
                for k, v in loaded_cooldowns.items():
                    exp_time = datetime.fromisoformat(v)
                    if now < exp_time:
                        cooldowns[int(k)] = exp_time
                last_tested_data = {int(k): v for k, v in data.get("last_tested_data", {}).items()}
            print("Database loaded successfully!")
        except Exception as e:
            print(f"Error loading database: {e}")

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

def get_remaining_cooldown(member_id):
    if member_id in cooldowns:
        expiration = cooldowns[member_id]
        now = datetime.utcnow()
        if now < expiration:
            delta = expiration - now
            days = delta.days
            hours, remainder = divmod(delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            parts = []
            if days > 0: parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0: parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0: parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            return ", ".join(parts) if parts else "a few seconds"
        else:
            del cooldowns[member_id]
            save_data()
    return None

async def log_to_staff(guild, text):
    log_channel = discord.utils.get(guild.text_channels, name=STAFF_LOG_CHANNEL_NAME)
    if log_channel:
        try: await log_channel.send(f"📋 **[LOG]:** {text}")
        except Exception: pass

def generate_queue_embed(gamemode):
    title_status = "Tester(s) Available!" if active_testers[gamemode] else "Waiting for Tester(s)..."
    queue_list = ""
    if not queues[gamemode]:
        queue_list = "*Empty*"
    else:
        for idx, player in enumerate(queues[gamemode], start=1):
            queue_list += f"{idx}. <@{player['user_id']}>\n"
    tester_mention = f"<@{active_testers[gamemode]}>" if active_testers[gamemode] else "*None*"
    embed = discord.Embed(
        title=title_status,
        description=f"⚪ The queue updates automatically.\nUse `/leave` if you wish to be removed from the waitlist or queue.\n\n"
                    f"**__Queue__ ({len(queues[gamemode])}/20):**\n{queue_list}\n\n"
                    f"**Active Testers:**\n{tester_mention}",
        color=0x5865f2
    )
    return embed

async def update_board_message(guild, gamemode):
    waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{gamemode.lower()}")
    if waitlist_channel:
        async for message in waitlist_channel.history(limit=20):
            if message.author == bot.user and message.embeds and ("Tester(s)" in message.embeds[0].title or "Waiting for Tester" in message.embeds[0].title):
                refreshed_embed = generate_queue_embed(gamemode)
                await message.edit(embed=refreshed_embed, view=StaffControlView(gamemode))
                break

async def afk_queue_remover(user_id, gamemode, guild_id):
    await asyncio.sleep(1200)
    guild = bot.get_guild(guild_id)
    if not guild: return
    if gamemode in queues:
        player_entry = next((p for p in queues[gamemode] if p['user_id'] == user_id), None)
        if player_entry and active_testers[gamemode] is None:
            queues[gamemode].remove(player_entry)
            save_data()
            await update_board_message(guild, gamemode)
            member = guild.get_member(user_id)
            if member:
                try: await member.send(f"⚠️ You have been removed from the **{gamemode}** queue due to inactivity.")
                except Exception: pass

class FastResultModal(discord.ui.Modal, title="Fast Test Evaluation"):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.region = discord.ui.TextInput(label="Region", placeholder="e.g. EU, NA", default="EU", required=True)
        self.prev_rank = discord.ui.TextInput(label="Previous Rank", placeholder="e.g. Unranked", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. High Tier 2", required=True)
        self.add_item(self.region)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        prev_rank_val = self.prev_rank.value.strip()
        region_val = self.region.value.upper().strip()
        clean_mc_name = self.mc_name.strip()
        skin_url = "https://render.crafty.gg/3d/bust/866125ad5e2b474e987654b6138d4f45"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://api.mojang.com/users/profiles/minecraft/{clean_mc_name}") as r:
                    if r.status == 200:
                        data = await r.json()
                        uuid = data.get("id")
                        skin_url = f"https://render.crafty.gg/3d/bust/{uuid}"
            except Exception:
                skin_url = f"https://mc-heads.net/player/{clean_mc_name}/512.png"
        
        embed = discord.Embed(color=0x5865f2)
        embed.set_author(name=f"{guild.name}'s Test Results 🏆", icon_url=guild.icon.url if guild.icon else None)
        embed.set_thumbnail(url=skin_url)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Region:", value=region_val, inline=False)
        embed.add_field(name="Username:", value=f"{clean_mc_name}", inline=False)
        embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=False)
        embed.add_field(name="Rank Earned:", value=rank_earned, inline=False)
        
        high_tier_keywords = ["HT3", "HT2", "HT1", "LT1", "LT2", "Tier 1", "Tier 2", "Tier 3"]
        is_high = any(k.lower() in rank_earned.lower() for k in high_tier_keywords)
        channel_name = "🥇│hight-results" if is_high else "🏆│results"
        
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if target_channel:
            if is_high:
                content_msg = f"{interaction.user.mention} - {clean_mc_name} - Promoted to **{rank_earned}**"
                msg = await target_channel.send(content=content_msg)
            else:
                msg = await target_channel.send(content=self.player_member.mention, embed=embed)
            for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await msg.add_reaction(emo)
                except Exception: pass
        
        player_entry = next((p for p in queues[self.gamemode] if p['user_id'] == self.player_member.id), None)
        if player_entry:
            queues[self.gamemode].remove(player_entry)
            
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)
        last_tested_data[self.player_member.id] = {
            "gamemode": self.gamemode,
            "timestamp": datetime.utcnow().isoformat(),
            "rank": rank_earned
        }
        save_data()

        for role in self.player_member.roles:
            if role.name.endswith(f" {self.gamemode}"):
                try: await self.player_member.remove_roles(role)
                except: pass

        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.default())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        await update_board_message(guild, self.gamemode)
        await log_to_staff(guild, f"Tester {interaction.user.mention} evaluated {self.player_member.mention} to **{rank_earned}**.")
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

class RetierModal(discord.ui.Modal, title="Retier Request"):
    gamemode_input = discord.ui.TextInput(label="Gamemode to Retier from", placeholder="e.g. Sword", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        gm = self.gamemode_input.value.strip().capitalize()
        if gm not in GAMEMODES:
            await interaction.response.send_message(f"❌ Invalid gamemode. Choose from: {', '.join(GAMEMODES)}", ephemeral=True)
            return

        user_data = last_tested_data.get(user_id)
        if not user_data or user_data.get("gamemode") != gm:
            await interaction.response.send_message("❌ You have no recent record or test found for this gamemode to retier from.", ephemeral=True)
            return

        last_time = datetime.fromisoformat(user_data["timestamp"])
        if datetime.utcnow() - last_time > timedelta(days=35):
            await interaction.response.send_message("❌ You can only retier within 35 days of your last test/evaluation.", ephemeral=True)
            return

        remaining = get_remaining_cooldown(user_id)
        if remaining is not None:
            await interaction.response.send_message(f"❌ You are on cooldown: {remaining}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        old_rank = user_data.get("rank", "Unknown")
        retier_rank_name = f"R{old_rank} {gm}"

        for role in interaction.user.roles:
            if role.name.endswith(f" {gm}"):
                try: await interaction.user.remove_roles(role)
                except: pass

        role = discord.utils.get(guild.roles, name=retier_rank_name)
        if not role:
            try:
                role = await guild.create_role(name=retier_rank_name, mentionable=True, color=discord.Color.light_gray())
            except Exception:
                pass
        if role:
            try: await interaction.user.add_roles(role)
            except Exception: pass

        high_tier_keywords = ["HT3", "HT2", "HT1", "LT1", "LT2", "Tier 1", "Tier 2", "Tier 3"]
        is_high = any(k.lower() in old_rank.lower() for k in high_tier_keywords)
        channel_name = "🥇│hight-results" if is_high else "🏆│results"
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)

        if target_channel:
            if is_high:
                await target_channel.send(content=f"{interaction.user.mention} - Retired from {old_rank} {gm} (Assigned **{retier_rank_name}**)")
            else:
                embed = discord.Embed(title="Player Retier 🔄", description=f"{interaction.user.mention} has officially retired from **{gm}** ({old_rank} -> {retier_rank_name}).", color=0x99aab5)
                await target_channel.send(embed=embed)

        cooldowns[user_id] = datetime.utcnow() + timedelta(days=30)
        del last_tested_data[user_id]
        save_data()

        await interaction.followup.send(f"✅ Successfully processed your retier for **{gm}**. Assigned role: `{retier_rank_name}`.", ephemeral=True)
        await log_to_staff(guild, f"Player {interaction.user.mention} performed a Retier for **{gm}** (Old rank was {old_rank}).")

class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green, custom_id="tester_eval_secret_btn")
    async def open_eval_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_tester_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_tester_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Unauthorized staff!", ephemeral=True)
            return
        await interaction.response.send_modal(FastResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id))

class StaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.join_tester_btn.custom_id = f"p_join_btn_{gamemode.lower()}"
        self.next_player_btn.custom_id = f"p_next_btn_{gamemode.lower()}"
        self.leave_session_btn.custom_id = f"p_leave_btn_{gamemode.lower()}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple)
    async def join_tester_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if active_testers[self.gamemode] is not None:
            await interaction.response.send_message("❌ Tester active.", ephemeral=True)
            return
        active_testers[self.gamemode] = interaction.user.id
        await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)
        await log_to_staff(interaction.guild, f"{interaction.user.mention} active tester for **{self.gamemode}**.")

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if active_testers[self.gamemode] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Join first.", ephemeral=True)
            return
        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ Empty queue.", ephemeral=True)
            return

        current_player_data = queues[self.gamemode][0]
        guild = interaction.guild
        player_member = guild.get_member(current_player_data['user_id'])
        if not player_member:
            queues[self.gamemode].pop(0)
            save_data()
            await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)
            return

        expected_room_name = f"🔒-match-{self.gamemode.lower()}-{player_member.name}".lower()
        if discord.utils.get(guild.text_channels, name=expected_room_name):
            await interaction.response.send_message("❌ Channel already exists.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category: category = await guild.create_category("🎯Tierlist")

        private_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        match_room = await guild.create_text_channel(name=expected_room_name, category=category, overwrites=private_overwrites)
        eval_view = TesterPrivateEvalView(player_member, current_player_data['mc_name'], self.gamemode, match_room.id)
        await match_room.send(content=f"⚡ **Match Room:** {player_member.mention} vs {interaction.user.mention}", view=eval_view)
        await log_to_staff(guild, f"Tester {interaction.user.mention} opened match room {match_room.mention} with {player_member.mention}.")
        await interaction.message.edit(embed=generate_queue_embed(self.gamemode), view=self)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if active_testers[self.gamemode] != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Not active.", ephemeral=True)
            return
        active_testers[self.gamemode] = None
        await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)
        await log_to_staff(interaction.guild, f"{interaction.user.mention} left session on **{self.gamemode}**.")

class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Enter your Minecraft Username", placeholder="e.g. Stev3_", required=True)
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if len(queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ Queue full.", ephemeral=True)
            return
        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ Queued elsewhere.", ephemeral=True)
            return
        remaining = get_remaining_cooldown(user_id)
        if remaining is not None:
            await interaction.response.send_message(f"❌ Cooldown active: {remaining}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        queues[self.gamemode].append({'user_id': user_id, 'mc_name': self.mc_name.value})
        save_data()
        if active_testers[self.gamemode] is None:
            asyncio.create_task(afk_queue_remover(user_id, self.gamemode, interaction.guild.id))
        waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        if waitlist_channel:
            await waitlist_channel.set_permissions(interaction.user, read_messages=True, send_messages=False)
            await update_board_message(interaction.guild, self.gamemode)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to test...", options=options, row=0)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values[0]))

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

    @discord.ui.button(label="🔄 Retier", style=discord.ButtonStyle.secondary, custom_id="main_retier_btn", row=1)
    async def retier_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        user_data = last_tested_data.get(user_id)
        
        if not user_data:
            await interaction.response.send_message("❌ You are not eligible for a retier (no recent test record found within 35 days).", ephemeral=True)
            return
            
        last_time = datetime.fromisoformat(user_data["timestamp"])
        if datetime.utcnow() - last_time > timedelta(days=35):
            await interaction.response.send_message("❌ Your last test was more than 35 days ago. You can no longer retier.", ephemeral=True)
            return
            
        await interaction.response.send_modal(RetierModal())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    for gm in GAMEMODES: bot.add_view(StaffControlView(gm))
    bot.add_view(MainTicketView())
    await bot.tree.sync()

@bot.tree.command(name="setup_panel", description="Generate the main booking panel")
async def setup_panel(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(title="⚔️ Request a Tierlist Test", description="Select a mode or use the Retier option below if eligible.", color=0x5865f2), view=MainTicketView())

@bot.tree.command(name="setup_board", description="Create the live board")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    await interaction.response.defer(ephemeral=True)
    category = discord.utils.get(interaction.guild.categories, name="🎯Tierlist") or await interaction.guild.create_category("🎯Tierlist")
    waitlist_channel = await interaction.guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
    await interaction.delete_original_response()

# Avvio sicuro ed eseguito in parallelo per non bloccare i server di hosting
if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ.get("DISCORD_TOKEN"))
