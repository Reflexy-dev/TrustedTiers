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

app = Flask('')

@app.route('/')
def home():
    return "Bot is online!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
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
retire_cooldowns = {}
active_testers = {gm: None for gm in GAMEMODES}

def save_data():
    try:
        data = {
            "queues": queues,
            "cooldowns": {str(k): v.isoformat() for k, v in cooldowns.items()},
            "retire_cooldowns": {str(k): v.isoformat() for k, v in retire_cooldowns.items()}
        }
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving database: {e}")

def load_data():
    global queues, cooldowns, retire_cooldowns
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
                        
                loaded_retire = data.get("retire_cooldowns", {})
                for k, v in loaded_retire.items():
                    exp_time = datetime.fromisoformat(v)
                    if now < exp_time:
                        retire_cooldowns[int(k)] = exp_time
                        
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

def get_remaining_retire_cooldown(member_id):
    if member_id in retire_cooldowns:
        expiration = retire_cooldowns[member_id]
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
            del retire_cooldowns[member_id]
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
            queue_list += f"{idx}. <@{player['user_id']}> ({player['region']})\n"
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

def is_high_tier(tier_string):
    tier_string = tier_string.strip().lower()
    high_keywords = ["ht1", "ht2", "ht3", "lt1", "lt2", "tier 1", "tier 2", "tier 3", "t1", "t2", "t3"]
    return any(k in tier_string for k in high_keywords)

class FastResultModal(discord.ui.Modal, title="Fast Test Evaluation"):
    def __init__(self, player_member, mc_name, region, gamemode, ticket_channel_id):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.region = region
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.prev_rank = discord.ui.TextInput(label="Previous Rank", placeholder="e.g. Unranked", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. HT2", required=True)
        self.status_result = discord.ui.TextInput(label="Status (Passed / Failed)", placeholder="Passed", default="Passed", required=True)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)
        self.add_item(self.status_result)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        prev_rank_val = self.prev_rank.value.strip()
        status_val = self.status_result.value.strip()
        clean_mc_name = self.mc_name.strip()
        region_val = self.region.upper().strip()
        
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
        embed.add_field(name="Tester", value=interaction.user.mention, inline=False)
        embed.add_field(name="Region", value=region_val, inline=False)
        embed.add_field(name="Username", value=clean_mc_name, inline=False)
        embed.add_field(name="Previous Rank", value=prev_rank_val, inline=False)
        embed.add_field(name="Rank Earned", value=rank_earned, inline=False)
        embed.add_field(name="Status", value=status_val, inline=False)
        
        is_high = is_high_tier(rank_earned)
        channel_name = "🥇│hight-results" if is_high else "🏆│results"
        
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if target_channel:
            msg = await target_channel.send(content=self.player_member.mention, embed=embed)
            for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await msg.add_reaction(emo)
                except Exception: pass
        
        player_entry = next((p for p in queues[self.gamemode] if p['user_id'] == self.player_member.id), None)
        if player_entry:
            queues[self.gamemode].remove(player_entry)
            
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=35)
        save_data()

        for role in self.player_member.roles:
            if role.name.endswith(f" {self.gamemode}") or (role.name.startswith("R") and role.name.endswith(f" {self.gamemode}")):
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

class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, region, gamemode, channel_id):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.region = region
        self.gamemode = gamemode
        self.channel_id = channel_id

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green, custom_id="tester_eval_secret_btn")
    async def open_eval_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_tester_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_tester_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Unauthorized staff!", ephemeral=True)
            return
        await interaction.response.send_modal(FastResultModal(self.player_member, self.mc_name, self.region, self.gamemode, self.channel_id))

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
        eval_view = TesterPrivateEvalView(player_member, current_player_data['mc_name'], current_player_data['region'], self.gamemode, match_room.id)
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
    region = discord.ui.TextInput(label="Region", placeholder="e.g. EU, NA", default="EU", required=True)
    
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
            await interaction.response.send_message(f"❌ Cooldown active: {remaining} before you can test again.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        queues[self.gamemode].append({
            'user_id': user_id, 
            'mc_name': self.mc_name.value.strip(),
            'region': self.region.value.upper().strip()
        })
        save_data()
        if active_testers[self.gamemode] is None:
            asyncio.create_task(afk_queue_remover(user_id, self.gamemode, interaction.guild.id))
        waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        if waitlist_channel:
            await waitlist_channel.set_permissions(interaction.user, read_messages=True, send_messages=False)
            await update_board_message(interaction.guild, self.gamemode)
        await interaction.followup.send("✅ Successfully joined the queue!", ephemeral=True)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to test...", options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values[0]))

class RetireGamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to retire from...", options=options)
        
    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        remaining = get_remaining_retire_cooldown(user_id)
        if remaining is not None:
            await interaction.response.send_message(f"❌ Retire cooldown active: {remaining} remaining before you can retire again.", ephemeral=True)
            return
            
        guild = interaction.guild
        member = interaction.user
        chosen_gm = self.values[0]
        
        found_role = None
        current_tier_name = ""
        for role in member.roles:
            if role.name.endswith(f" {chosen_gm}") and not role.name.startswith("R"):
                found_role = role
                current_tier_name = role.name.replace(f" {chosen_gm}", "").strip()
                break
                
        if not found_role:
            await interaction.response.send_message(f"❌ You don't have an active rank role for **{chosen_gm}** to retire from.", ephemeral=True)
            return
            
        retire_role_name = f"R{current_tier_name} {chosen_gm}"
        retire_role = discord.utils.get(guild.roles, name=retire_role_name)
        if not retire_role:
            try:
                retire_role = await guild.create_role(name=retire_role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception:
                pass
                
        try:
            await member.remove_roles(found_role)
            if retire_role:
                await member.add_roles(retire_role)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to update roles: {e}", ephemeral=True)
            return
            
        retire_cooldowns[user_id] = datetime.utcnow() + timedelta(days=35)
        save_data()
        
        await log_to_staff(guild, f"User {member.mention} retired from **{chosen_gm}**, changing role to `{retire_role_name}`.")
        await interaction.response.send_message(f"✅ Successfully retired from **{chosen_gm}**! Your role has been updated to **{retire_role_name}**.", ephemeral=True)

class RetireView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RetireGamemodeSelect())

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

    @discord.ui.button(label="Request Tier Test", style=discord.ButtonStyle.primary, row=1, custom_id="main_request_tier_test_btn")
    async def request_tier_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Please select a gamemode below to configure your test:", view=MainTicketViewSelectorOnly(), ephemeral=True)

    @discord.ui.button(label="Retire", style=discord.ButtonStyle.secondary, row=1, custom_id="main_retire_btn")
    async def retire_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Please select a gamemode to retire from:", view=RetireView(), ephemeral=True)

class MainTicketViewSelectorOnly(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    for gm in GAMEMODES: bot.add_view(StaffControlView(gm))
    bot.add_view(MainTicketView())
    bot.add_view(RetireView())
    bot.add_view(MainTicketViewSelectorOnly())
    await bot.tree.sync()

@bot.tree.command(name="setup_panel", description="Generate the main booking panel")
async def setup_panel(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(title="⚔️ Request a Tierlist Test", description="Select an option below to request a test or retire from a tier.", color=0x5865f2), view=MainTicketView())

@bot.tree.command(name="setup_board", description="Create the live board")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    await interaction.response.defer(ephemeral=True)
    category = discord.utils.get(interaction.guild.categories, name="🎯Tierlist") or await interaction.guild.create_category("🎯Tierlist")
    waitlist_channel = await interaction.guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
    await interaction.delete_original_response()

bot.run(os.environ.get("DISCORD_TOKEN"))
