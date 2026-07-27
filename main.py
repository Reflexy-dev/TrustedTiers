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
retirements = {}  # {user_id: {gamemode: retirement_datetime}}
active_testers = {gm: None for gm in GAMEMODES}

def save_data():
    try:
        data = {
            "queues": queues,
            "cooldowns": {str(k): v.isoformat() for k, v in cooldowns.items()},
            "retirements": {str(k): {gm: dt.isoformat() for gm, dt in v.items()} for k, v in retirements.items()}
        }
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving database: {e}")

def load_data():
    global queues, cooldowns, retirements
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
                
                loaded_retirements = data.get("retirements", {})
                for k, v in loaded_retirements.items():
                    retirements[int(k)] = {gm: datetime.fromisoformat(dt) for gm, dt in v.items()}
                    
            print("Database loaded successfully!")
        except Exception as e:
            print(f"Error loading database: {e}")

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

def is_tester_active_anywhere(user_id):
    for gm, tester_id in active_testers.items():
        if tester_id == user_id:
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
            queue_list += f"{idx}. <@{player['user_id']}> ({player.get('region', 'N/A')})\n"
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
            waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{gamemode.lower()}")
            if waitlist_channel:
                member = guild.get_member(user_id)
                if member:
                    try: await waitlist_channel.set_permissions(member, overwrite=None)
                    except Exception: pass
            member = guild.get_member(user_id)
            if member:
                try: await member.send(f"⚠️ You have been removed from the **{gamemode}** queue due to inactivity.")
                except Exception: pass

def is_high_tier(rank_earned: str) -> bool:
    rank_lower = rank_earned.lower()
    high_keywords = ["lt1", "ht1", "lt2", "ht2", "lt3", "tier 1", "tier 2", "tier 3"]
    if any(k in rank_lower for k in high_keywords):
        if "ht3" in rank_lower or "tier 3" in rank_lower:
            return "high" in rank_lower or "ht3" in rank_lower
        return True
    return False

class FastResultModal(discord.ui.Modal, title="Fast Test Evaluation"):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id, region):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.region = region
        
        self.prev_rank = discord.ui.TextInput(label="Previous Rank", placeholder="e.g. Unranked", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. High Tier 3", required=True)
        self.match_score = discord.ui.TextInput(label="Match Score (Required for HT3+)", placeholder="e.g. Won 4-1 vs. opponent", required=False)
        
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)
        self.add_item(self.match_score)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        prev_rank_val = self.prev_rank.value.strip()
        clean_mc_name = self.mc_name.strip()
        score_val = self.match_score.value.strip()

        is_high = is_high_tier(rank_earned)
        if is_high and not score_val:
            await interaction.followup.send("❌ You must provide the match score for High Tier 3 or above evaluations!", ephemeral=True)
            return

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

        if is_high:
            content_msg = f"{self.player_member.mention} - {clean_mc_name} - Promoted to **{rank_earned}**\n\n**Passed Evaluation**\n\n**{rank_earned} Fights**\n| {score_val}"
            target_channel = discord.utils.get(guild.text_channels, name="🥇│hight-results")
            if target_channel:
                msg = await target_channel.send(content=content_msg)
                for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                    try: await msg.add_reaction(emo)
                    except Exception: pass
        else:
            embed = discord.Embed(color=0x5865f2)
            embed.set_author(name=f"{guild.name}'s Test Results 🏆", icon_url=guild.icon.url if guild.icon else None)
            embed.set_thumbnail(url=skin_url)
            embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
            embed.add_field(name="Region:", value=self.region, inline=False)
            embed.add_field(name="Username:", value=f"{clean_mc_name}", inline=False)
            embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=False)
            embed.add_field(name="Rank Earned:", value=rank_earned, inline=False)
            target_channel = discord.utils.get(guild.text_channels, name="🏆│results")
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
            if role.name.endswith(f" {self.gamemode}"):
                try: await self.player_member.remove_roles(role)
                except: pass

        prefix = "R" if self.player_member.id in retirements and self.gamemode in retirements[self.player_member.id] else ""
        role_name = f"{prefix}{rank_earned} {self.gamemode}".strip()
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.default())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        if waitlist_channel:
            try: await waitlist_channel.set_permissions(self.player_member, overwrite=None)
            except Exception: pass

        await update_board_message(guild, self.gamemode)
        await log_to_staff(guild, f"Tester {interaction.user.mention} evaluated {self.player_member.mention} to **{rank_earned}**.")
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id, region):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region = region

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green, custom_id="tester_eval_secret_btn")
    async def open_eval_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_tester_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_tester_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Unauthorized staff!", ephemeral=True)
            return
        await interaction.response.send_modal(FastResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region))

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
        if is_tester_active_anywhere(interaction.user.id) and active_testers[self.gamemode] != interaction.user.id:
            await interaction.response.send_message("❌ You are already active as a tester in another gamemode queue!", ephemeral=True)
            return
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
        eval_view = TesterPrivateEvalView(player_member, current_player_data['mc_name'], self.gamemode, match_room.id, current_player_data.get('region', 'EU'))
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
    mc_name = discord.ui.TextInput(label="Minecraft Username", placeholder="e.g. Stev3_", required=True)
    region = discord.ui.TextInput(label="Region", placeholder="e.g. EU, NA, ASIA", default="EU", required=True)

    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        is_owner = await bot.is_owner(interaction.user) or interaction.user.guild_permissions.administrator
        
        if len(queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ Queue full.", ephemeral=True)
            return
        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ Queued elsewhere.", ephemeral=True)
            return
        
        if not is_owner:
            remaining = get_remaining_cooldown(user_id)
            if remaining is not None:
                await interaction.response.send_message(f"❌ Cooldown active: {remaining}", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)
        queues[self.gamemode].append({
            'user_id': user_id, 
            'mc_name': self.mc_name.value,
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
        choice = self.values[0]
        await interaction.response.send_modal(MinecraftNameModal(choice))

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    for gm in GAMEMODES: bot.add_view(StaffControlView(gm))
    bot.add_view(MainTicketView())
    await bot.tree.sync()

@bot.tree.command(name="setup_panel", description="Generate the main booking panel")
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select a mode from the dropdown menu below to register for testing.",
        color=0x5865f2
    )
    await interaction.response.send_message(embed=embed, view=MainTicketView())

@bot.tree.command(name="setup_board", description="Create the live board")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    await interaction.response.defer(ephemeral=True)
    category = discord.utils.get(interaction.guild.categories, name="🎯Tierlist") or await interaction.guild.create_category("🎯Tierlist")
    waitlist_channel = await interaction.guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
    await interaction.delete_original_response()

@bot.tree.command(name="leave", description="Leave your current queue or waitlist")
async def leave_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    found = False
    for gm in GAMEMODES:
        player_entry = next((p for p in queues[gm] if p['user_id'] == user_id), None)
        if player_entry:
            queues[gm].remove(player_entry)
            found = True
            save_data()
            await update_board_message(interaction.guild, gm)
            waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{gm.lower()}")
            if waitlist_channel:
                try: await waitlist_channel.set_permissions(interaction.user, overwrite=None)
                except Exception: pass
    
    if found:
        await interaction.response.send_message("✅ You have been removed from the queue.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not in any queue.", ephemeral=True)

@bot.tree.command(name="kickqueue", description="Kick a user from a specific gamemode queue (Staff only)")
@app_commands.describe(gamemode="The gamemode queue", member="The member to kick")
async def kickqueue(interaction: discord.Interaction, gamemode: str, member: discord.Member):
    has_role = any(role.name == f"Tester {gamemode}" for role in interaction.user.roles)
    if not (has_role or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You are not authorized to manage this queue.", ephemeral=True)
        return

    if gamemode not in GAMEMODES:
        await interaction.response.send_message("❌ Invalid gamemode.", ephemeral=True)
        return

    player_entry = next((p for p in queues[gamemode] if p['user_id'] == member.id), None)
    if player_entry:
        queues[gamemode].remove(player_entry)
        save_data()
        await update_board_message(interaction.guild, gamemode)
        waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{gamemode.lower()}")
        if waitlist_channel:
            try: await waitlist_channel.set_permissions(member, overwrite=None)
            except Exception: pass
        await interaction.response.send_message(f"✅ Successfully kicked {member.mention} from the **{gamemode}** queue.", ephemeral=True)
        try: await member.send(f"⚠️ You have been kicked from the **{gamemode}** queue by a staff member.")
        except Exception: pass
    else:
        await interaction.response.send_message(f"❌ {member.mention} is not in the **{gamemode}** queue.", ephemeral=True)

@bot.tree.command(name="retier", description="Retire from a gamemode test status")
@app_commands.describe(gamemodes="Comma-separated list of gamemodes (e.g. Sword, UHC)")
async def retier(interaction: discord.Interaction, gamemodes: str):
    user_id = interaction.user.id
    user_retirements = retirements.setdefault(user_id, {})
    now = datetime.utcnow()
    
    gims = [g.strip().capitalize() for g in gamemodes.split(",")]
    success = []
    failed = []

    for gm in gims:
        if gm not in GAMEMODES:
            failed.append(f"{gm} (Invalid)")
            continue
        
        user_cd_expiry = cooldowns.get(user_id)
        if user_cd_expiry and now < user_cd_expiry:
            failed.append(f"{gm} (Must wait 35 days after your test)")
            continue
        
        user_retirements[gm] = now
        success.append(gm)

        for role in interaction.user.roles:
            if role.name.endswith(f" {gm}") and not role.name.startswith("R"):
                try:
                    await interaction.user.remove_roles(role)
                    new_role_name = f"R{role.name}"
                    new_role = discord.utils.get(interaction.guild.roles, name=new_role_name)
                    if not new_role:
                        new_role = await interaction.guild.create_role(name=new_role_name, mentionable=True, color=role.color)
                    await interaction.user.add_roles(new_role)
                except Exception:
                    pass

    save_data()
    msg = []
    if success:
        msg.append(f"✅ Successfully retired from: {', '.join(success)}")
    if failed:
        msg.append(f"❌ Failed for: {', '.join(failed)}")
    
    await interaction.response.send_message("\n".join(msg), ephemeral=True)

@bot.unretire = bot.tree.command(name="unretire", description="Cancel your retirement after 35 days")
@app_commands.describe(gamemodes="Comma-separated list of gamemodes (e.g. Sword, UHC)")
async def unretire_cmd(interaction: discord.Interaction, gamemodes: str):
    user_id = interaction.user.id
    user_retirements = retirements.get(user_id, {})
    now = datetime.utcnow()
    
    gims = [g.strip().capitalize() for g in gamemodes.split(",")]
    success = []
    failed = []

    for gm in gims:
        if gm not in user_retirements:
            failed.append(f"{gm} (Not retired)")
            continue
        
        retire_time = user_retirements[gm]
        if now < retire_time + timedelta(days=35):
            failed.append(f"{gm} (Must wait 35 days since retirement)")
            continue
        
        del user_retirements[gm]
        success.append(gm)

        for role in interaction.user.roles:
            if role.name.endswith(f" {gm}") and role.name.startswith("R"):
                try:
                    await interaction.user.remove_roles(role)
                    new_role_name = role.name[1:]
                    new_role = discord.utils.get(interaction.guild.roles, name=new_role_name)
                    if not new_role:
                        new_role = await interaction.guild.create_role(name=new_role_name, mentionable=True, color=role.color)
                    await interaction.user.add_roles(new_role)
                except Exception:
                    pass

    if not user_retirements and user_id in retirements:
        del retirements[user_id]

    save_data()
    msg = []
    if success:
        msg.append(f"✅ Successfully unretired from: {', '.join(success)}")
    if failed:
        msg.append(f"❌ Failed for: {', '.join(failed)}")
    
    await interaction.response.send_message("\n".join(msg), ephemeral=True)

bot.run(os.environ.get("DISCORD_TOKEN"))
