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
retirements = {}       
last_test_dates = {}   
active_testers = {gm: None for gm in GAMEMODES}

def save_data():
    try:
        data = {
            "queues": queues,
            "cooldowns": {str(k): v.isoformat() for k, v in cooldowns.items()},
            "retirements": retirements,
            "last_test_dates": last_test_dates
        }
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving database: {e}")

def load_data():
    global queues, cooldowns, retirements, last_test_dates
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
                        
                retirements = data.get("retirements", {})
                last_test_dates = data.get("last_test_dates", {})
            print("Database loaded successfully!")
        except Exception as e:
            print(f"Error loading database: {e}")

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

def get_remaining_cooldown(member_id, guild=None, user=None):
    # Bypass per l'owner del server o amministratori
    if guild and user:
        if guild.owner_id == user.id or user.guild_permissions.administrator:
            return None

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
            queue_list += f"{idx}. <@{player['user_id']}> (Region: **{player.get('region', 'EU')}**)\n"
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
    def __init__(self, player_member, mc_name, gamemode, channel_id, region_val, is_high):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region_val = region_val
        self.is_high = is_high

        self.new_rank = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. High Tier 3, HT2", required=True)
        self.add_item(self.new_rank)

        if self.is_high:
            self.eval_status = discord.ui.TextInput(label="Evaluation Status", placeholder="Passed Evaluation / Failed Evaluation", default="Passed Evaluation", required=True)
            self.fight_category = discord.ui.TextInput(label="Fight Category Title", placeholder="e.g. HT3 Fights", default="HT3 Fights", required=True)
            self.fight_details = discord.ui.TextInput(label="Match Details", placeholder="Won 4-1 vs. opponent", default="Won 4-1 vs. ", required=True)
            self.add_item(self.eval_status)
            self.add_item(self.fight_category)
            self.add_item(self.fight_details)
        else:
            self.prev_rank = discord.ui.TextInput(label="Previous Rank", placeholder="e.g. Unranked", default="Unranked", required=True)
            self.add_item(self.prev_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        clean_mc_name = self.mc_name.strip()

        if self.is_high:
            status_text = self.eval_status.value.strip()
            category_text = self.fight_category.value.strip()
            details_text = self.fight_details.value.strip()
            
            content_message = f"{self.player_member.mention} - {clean_mc_name} - Promoted to **{rank_earned}**\n\n__{status_text}__\n\n**{category_text}**\n> {details_text}"
            target_channel = discord.utils.get(guild.text_channels, name="🥇│hight-results")
            if target_channel:
                await target_channel.send(content_message)
        else:
            prev_rank_val = self.prev_rank.value.strip()
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
            embed.add_field(name="Region:", value=self.region_val, inline=False)
            embed.add_field(name="Username:", value=clean_mc_name, inline=False)
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
            
        now_utc = datetime.utcnow()
        cooldowns[self.player_member.id] = now_utc + timedelta(days=7)
        
        user_str = str(self.player_member.id)
        if user_str not in last_test_dates:
            last_test_dates[user_str] = {}
        last_test_dates[user_str][self.gamemode] = now_utc.isoformat()
        
        if user_str in retirements and self.gamemode in retirements[user_str]:
            del retirements[user_str][self.gamemode]
            
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
        match_channel = guild.get_channel(self.channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id, region_val):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region_val = region_val

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green, custom_id="tester_eval_secret_btn")
    async def open_eval_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        has_tester_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_tester_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Unauthorized staff!", ephemeral=True)
            return
        await interaction.response.send_modal(FastResultEvalRouter(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region_val))

class FastResultEvalRouter(discord.ui.Modal, title="Select Evaluation Type"):
    tier_input = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. High Tier 3, HT2, LT4", required=True)

    def __init__(self, player_member, mc_name, gamemode, channel_id, region_val):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region_val = region_val

    async def on_submit(self, interaction: discord.Interaction):
        rank_val = self.tier_input.value.strip().lower()
        ht_keywords = ["ht1", "ht2", "ht3", "lt1", "lt2", "high tier", "tier 1", "tier 2", "tier 3"]
        is_high = any(k in rank_val for k in ht_keywords)
        
        modal = FastResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region_val, is_high)
        modal.new_rank.default = self.tier_input.value.strip()
        await interaction.response.send_modal(modal)

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
        if len(queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ Queue full.", ephemeral=True)
            return
        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ Queued elsewhere.", ephemeral=True)
            return
        remaining = get_remaining_cooldown(user_id, interaction.guild, interaction.user)
        if remaining is not None:
            await interaction.response.send_message(f"❌ Cooldown active: {remaining}", ephemeral=True)
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
        await interaction.followup.send(f"✅ Successfully joined the **{self.gamemode}** queue!", ephemeral=True)

class RetirementModal(discord.ui.Modal, title="Retirement Request"):
    confirmation = discord.ui.TextInput(label="Type 'CONFIRM' to retire", placeholder="CONFIRM", required=True)

    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirmation.value.strip().upper() != "CONFIRM":
            await interaction.response.send_message("❌ Retirement cancelled. You must type CONFIRM.", ephemeral=True)
            return
        
        user_str = str(interaction.user.id)
        if user_str not in retirements:
            retirements[user_str] = {}
        retirements[user_str][self.gamemode] = datetime.utcnow().isoformat()
        save_data()

        for role in interaction.user.roles:
            if role.name.endswith(f" {self.gamemode}"):
                try: await interaction.user.remove_roles(role)
                except: pass

        retired_role_name = f"Retired {self.gamemode}"
        r_role = discord.utils.get(interaction.guild.roles, name=retired_role_name)
        if not r_role:
            try: r_role = await interaction.guild.create_role(name=retired_role_name, color=discord.Color.dark_grey())
            except: pass
        if r_role:
            try: await interaction.user.add_roles(r_role)
            except: pass

        await interaction.response.send_message(f"✅ You have successfully retired from **{self.gamemode}**.", ephemeral=True)
        await log_to_staff(interaction.guild, f"{interaction.user.mention} has retired from **{self.gamemode}**.")

class UnretierModal(discord.ui.Modal, title="Unretier Request"):
    confirmation = discord.ui.TextInput(label="Type 'UNRETIER' to come back", placeholder="UNRETIER", required=True)

    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirmation.value.strip().upper() != "UNRETIER":
            await interaction.response.send_message("❌ Unretier cancelled. You must type UNRETIER.", ephemeral=True)
            return

        user_str = str(interaction.user.id)
        if user_str in retirements and self.gamemode in retirements[user_str]:
            del retirements[user_str][self.gamemode]
            save_data()

        retired_role_name = f"Retired {self.gamemode}"
        r_role = discord.utils.get(interaction.guild.roles, name=retired_role_name)
        if r_role and r_role in interaction.user.roles:
            try: await interaction.user.remove_roles(r_role)
            except: pass

        await interaction.response.send_message(f"✅ You have successfully unretired from **{self.gamemode}**! You can now request tests again.", ephemeral=True)
        await log_to_staff(interaction.guild, f"{interaction.user.mention} unretired from **{self.gamemode}**.")

class GamemodeSelect(discord.ui.Select):
    def __init__(self, user_id):
        now = datetime.utcnow()
        user_str = str(user_id)
        options = []
        
        for gm in GAMEMODES:
            is_retired = user_str in retirements and gm in retirements[user_str]
            
            can_retire = False
            if user_str in last_test_dates and gm in last_test_dates[user_str]:
                last_test_time = datetime.fromisoformat(last_test_dates[user_str][gm])
                if (now - last_test_time).days >= 35 and not is_retired:
                    can_retire = True

            can_unretier = False
            if is_retired:
                ret_time = datetime.fromisoformat(retirements[user_str][gm])
                if (now - ret_time).days >= 35:
                    can_unretier = True

            if can_unretier:
                options.append(discord.SelectOption(label=f"Unretier: {gm}", value=f"unretier_{gm}", emoji="🔓", description="You can now unretier from this mode!"))
            elif can_retire:
                options.append(discord.SelectOption(label=f"Retirement: {gm}", value=f"retire_{gm}", emoji="⏳", description="Eligible for retirement (35+ days inactive)"))
            else:
                label_text = f"{gm} (Retired)" if is_retired else gm
                options.append(discord.SelectOption(label=label_text, value=f"test_{gm}", emoji=GAMEMODE_EMOJIS[gm]))

        super().__init__(placeholder="Choose an action or gamemode...", options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val.startswith("test_"):
            gm = val.replace("test_", "")
            user_str = str(interaction.user.id)
            if user_str in retirements and gm in retirements[user_str]:
                await interaction.response.send_message("❌ You are currently retired from this gamemode. You must unretier first.", ephemeral=True)
                return
            await interaction.response.send_modal(MinecraftNameModal(gm))
        elif val.startswith("retire_"):
            gm = val.replace("retire_", "")
            await interaction.response.send_modal(RetirementModal(gm))
        elif val.startswith("unretier_"):
            gm = val.replace("unretier_", "")
            await interaction.response.send_modal(UnretierModal(gm))

class MainTicketView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect(user_id))

# --- COMANDI UTENTE E STAFF AGGIUNTIVI ---

@bot.tree.command(name="leave", description="Leave your current queue or waitlist")
async def leave(interaction: discord.Interaction):
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
                except: pass
            break
            
    if found:
        await interaction.response.send_message("✅ You have successfully left the queue and waitlist.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not currently in any queue.", ephemeral=True)

@bot.tree.command(name="kick_queue", description="Kick a user from a specific gamemode queue (Staff only)")
@app_commands.describe(member="The user to kick", gamemode="The gamemode queue")
@app_commands.choices(gamemode=[app_commands.Choice(name=gm, value=gm) for gm in GAMEMODES])
async def kick_queue(interaction: discord.Interaction, member: discord.Member, gamemode: str):
    has_role = any(role.name == f"Tester {gamemode}" for role in interaction.user.roles)
    if not (has_role or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You are unauthorized to manage this queue.", ephemeral=True)
        return

    player_entry = next((p for p in queues[gamemode] if p['user_id'] == member.id), None)
    if player_entry:
        queues[gamemode].remove(player_entry)
        save_data()
        await update_board_message(interaction.guild, gamemode)
        waitlist_channel = discord.utils.get(interaction.guild.text_channels, name=f"waitlist-{gamemode.lower()}")
        if waitlist_channel:
            try: await waitlist_channel.set_permissions(member, overwrite=None)
            except: pass
        await interaction.response.send_message(f"✅ Successfully kicked {member.mention} from the **{gamemode}** queue.", ephemeral=True)
        await log_to_staff(interaction.guild, f"{interaction.user.mention} kicked {member.mention} from **{gamemode}** queue.")
    else:
        await interaction.response.send_message(f"❌ That user is not in the **{gamemode}** queue.", ephemeral=True)

class RetirementSelectView(discord.ui.View):
    def __init__(self, user_id, action_type):
        super().__init__(timeout=60)
        self.add_item(RetirementActionSelect(user_id, action_type))

class RetirementActionSelect(discord.ui.Select):
    def __init__(self, user_id, action_type):
        now = datetime.utcnow()
        user_str = str(user_id)
        options = []
        
        for gm in GAMEMODES:
            is_retired = user_str in retirements and gm in retirements[user_str]
            if action_type == "retire":
                if user_str in last_test_dates and gm in last_test_dates[user_str] and not is_retired:
                    last_test_time = datetime.fromisoformat(last_test_dates[user_str][gm])
                    if (now - last_test_time).days >= 35:
                        options.append(discord.SelectOption(label=gm, value=gm, emoji=GAMEMODE_EMOJIS[gm]))
            elif action_type == "unretier":
                if is_retired:
                    ret_time = datetime.fromisoformat(retirements[user_str][gm])
                    if (now - ret_time).days >= 35:
                        options.append(discord.SelectOption(label=gm, value=gm, emoji=GAMEMODE_EMOJIS[gm]))

        if not options:
            options.append(discord.SelectOption(label="No eligible gamemodes found", value="none", description="Requirements (35 days) not met yet."))
            
        super().__init__(placeholder="Select a gamemode...", options=options)
        self.action_type = action_type

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ No eligible gamemodes available for this action.", ephemeral=True)
            return
            
        gm = self.values[0]
        if self.action_type == "retire":
            await interaction.response.send_modal(RetirementModal(gm))
        else:
            await interaction.response.send_modal(UnretierModal(gm))

@bot.tree.command(name="retire", description="Retire from a gamemode (Available 35 days after your last test)")
async def retire_cmd(interaction: discord.Interaction):
    view = RetirementSelectView(interaction.user.id, "retire")
    await interaction.response.send_message("⏳ **Retirement Request:** Select the gamemode you want to retire from:", view=view, ephemeral=True)

@bot.tree.command(name="unretier", description="Unretier from a gamemode (Available 35 days after retirement)")
async def unretier_cmd(interaction: discord.Interaction):
    view = RetirementSelectView(interaction.user.id, "unretier")
    await interaction.response.send_message("🔓 **Unretier Request:** Select the gamemode you want to unretier from:", view=view, ephemeral=True)

@bot.tree.command(name="setup_panel", description="Generate the main booking panel")
async def setup_panel(interaction: discord.Interaction):
    view = MainTicketView(interaction.user.id)
    await interaction.response.send_message(embed=discord.Embed(title="⚔️ Request a Tierlist Test / Management", description="Select a mode or option from the menu below.", color=0x5865f2), view=view)

@bot.tree.command(name="setup_board", description="Create the live board")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    await interaction.response.defer(ephemeral=True)
    category = discord.utils.get(interaction.guild.categories, name="🎯Tierlist") or await interaction.guild.create_category("🎯Tierlist")
    waitlist_channel = await interaction.guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
    await interaction.delete_original_response()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    load_data()
    for gm in GAMEMODES: bot.add_view(StaffControlView(gm))
    print("Bot is fully ready and views registered!")

bot.run(os.environ.get("DISCORD_TOKEN"))
