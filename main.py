import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- MINI SERVER WEB PER RENDER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- CONFIGURAZIONE BOT ---
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

GAMEMODE_EMOJIS = {
    "Sword": "⚔️", "Axe": "🪓", "UHC": "🍎", "DiaPot": "💎", "NethPot": "🔥",
    "DiaSMP": "🛡️", "SMP": "🏡", "SpearMace": "🔱", "Mace": "🔨", "Cart": "🛒", "Crystal": "🔮"
}
GAMEMODES = list(GAMEMODE_EMOJIS.keys())

queues = {gm: [] for gm in GAMEMODES}
high_queues = {gm: [] for gm in GAMEMODES}

active_testers = {gm: None for gm in GAMEMODES}
active_high_testers = {gm: None for gm in GAMEMODES}

cooldowns = {}
CATEGORY_NAME = "🎯Tierlist"

TIER_ORDER = [
    "Unranked", "LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"
]

HIGH_TIERS_QUEUE = ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]

def get_current_rank(member: discord.Member, gamemode: str) -> str:
    for role in member.roles:
        for t in TIER_ORDER:
            if role.name == f"{t} {gamemode}":
                return t
    return "Unranked"

def is_valid_promotion(current_rank: str, target_rank: str):
    c_rank = current_rank.upper().strip()
    t_rank = target_rank.upper().strip()

    if c_rank not in TIER_ORDER or t_rank not in TIER_ORDER:
        return True, ""

    c_idx = TIER_ORDER.index(c_rank)
    t_idx = TIER_ORDER.index(t_rank)

    if t_idx > c_idx + 1:
        next_step = TIER_ORDER[c_idx + 1]
        return False, f"Invalid progression! The player is `{c_rank}` and can only advance to the next rank (`{next_step}`). They cannot skip directly to `{t_rank}`!"

    return True, ""

# --- FUNZIONE AGGIORNAMENTO FILE JSON LOCALE (PRENDE L'ULTIMO TIER DATO) ---
def update_json_file(guild: discord.Guild):
    players_data = []
    
    for member in guild.members:
        temp_tiers = {}
        # Scorriamo i ruoli del membro nell'ordine in cui Discord li restituisce (dal basso verso l'alto o viceversa, 
        # scorrendo la lista salviamo l'ultimo trovato in modo che l'ultimo assegnato sovrascriva i precedenti)
        for role in member.roles:
            for gm in GAMEMODES:
                for t in TIER_ORDER:
                    if role.name == f"{t} {gm}":
                        temp_tiers[gm] = t  # Sovrascrive sempre con l'ultimo ruolo trovato/assegnato
                                
        if temp_tiers:
            players_data.append({
                "discord_id": str(member.id),
                "discord_name": member.name,
                "display_name": member.display_name,
                "tiers": temp_tiers
            })
            
    try:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(players_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Errore salvataggio data.json: {e}")

# --- TASK BACKGROUND TIMEOUT CODA ---
@tasks.loop(minutes=1)
async def check_queue_timeouts():
    now = datetime.datetime.utcnow()
    for gm in GAMEMODES:
        updated = False
        new_queue = []
        for player in queues[gm]:
            if (now - player['joined_at']).total_seconds() > 3600:
                updated = True
                guild = bot.guilds[0] if bot.guilds else None
                if guild:
                    member = guild.get_member(player['user_id'])
                    if member:
                        w_chan = discord.utils.get(guild.text_channels, name=f"waitlist-{gm.lower()}")
                        if w_chan:
                            await w_chan.set_permissions(member, overwrite=None)
            else:
                new_queue.append(player)
        if updated:
            queues[gm] = new_queue
            for guild in bot.guilds:
                await update_board_message(guild, gm)

        h_updated = False
        new_h_queue = []
        for player in high_queues[gm]:
            if (now - player['joined_at']).total_seconds() > 3600:
                h_updated = True
                guild = bot.guilds[0] if bot.guilds else None
                if guild:
                    member = guild.get_member(player['user_id'])
                    if member:
                        w_chan = discord.utils.get(guild.text_channels, name=f"high-waitlist-{gm.lower()}")
                        if w_chan:
                            await w_chan.set_permissions(member, overwrite=None)
            else:
                new_h_queue.append(player)
        if h_updated:
            high_queues[gm] = new_h_queue
            for guild in bot.guilds:
                await update_high_board_message(guild, gm)

@check_queue_timeouts.before_loop
async def before_timeouts():
    await bot.wait_until_ready()

# --- MODALE INSERIMENTO NICK MINECRAFT (NORMALE) ---
class MinecraftNameModal(discord.ui.Modal):
    def __init__(self, gamemode: str):
        super().__init__(title=f"Queue: {gamemode}")
        self.gamemode = gamemode

        self.mc_name = discord.ui.TextInput(
            label="Minecraft Username",
            placeholder="Ex: Steve...",
            required=True
        )
        self.region = discord.ui.TextInput(
            label="Region",
            placeholder="EU, NA, AS...",
            default="EU",
            required=True,
            max_length=10
        )
        self.add_item(self.mc_name)
        self.add_item(self.region)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        if user_id in cooldowns and datetime.datetime.utcnow() < cooldowns[user_id]:
            remaining = (cooldowns[user_id] - datetime.datetime.utcnow()).days + 1
            await interaction.response.send_message(f"❌ You are on cooldown! You can join a queue again in about {remaining} day(s).", ephemeral=True)
            return

        if len(queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ The queue for this gamemode is full (max 20)!", ephemeral=True)
            return

        for gm, q in queues.items():
            if any(p['user_id'] == user_id for p in q):
                await interaction.response.send_message(f"❌ You are already in a queue!", ephemeral=True)
                return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value.strip(),
            'region': self.region.value.upper().strip(),
            'joined_at': datetime.datetime.utcnow()
        }

        queues[self.gamemode].append(player_data)
        guild = interaction.guild
        
        waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        if waitlist_channel:
            await waitlist_channel.set_permissions(interaction.user, read_messages=True, send_messages=False)

        await update_board_message(guild, self.gamemode)

# --- MODALE INSERIMENTO NICK MINECRAFT (HIGH TIERS) ---
class HighMinecraftNameModal(discord.ui.Modal):
    def __init__(self, gamemode: str):
        super().__init__(title=f"High Queue: {gamemode}")
        self.gamemode = gamemode

        self.mc_name = discord.ui.TextInput(
            label="Minecraft Username",
            placeholder="Ex: Steve...",
            required=True
        )
        self.region = discord.ui.TextInput(
            label="Region",
            placeholder="EU, NA, AS...",
            default="EU",
            required=True,
            max_length=10
        )
        self.add_item(self.mc_name)
        self.add_item(self.region)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        current_rank = get_current_rank(interaction.user, self.gamemode)

        if current_rank not in HIGH_TIERS_QUEUE:
            await interaction.response.send_message(f"❌ You must be at least **LT3** in `{self.gamemode}` to join this queue! Your rank: `{current_rank}`", ephemeral=True)
            return

        if user_id in cooldowns and datetime.datetime.utcnow() < cooldowns[user_id]:
            remaining = (cooldowns[user_id] - datetime.datetime.utcnow()).days + 1
            await interaction.response.send_message(f"❌ You are on cooldown! You can join a queue again in about {remaining} day(s).", ephemeral=True)
            return

        if len(high_queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ The High queue for this gamemode is full (max 20)!", ephemeral=True)
            return

        for gm, q in high_queues.items():
            if any(p['user_id'] == user_id for p in q):
                await interaction.response.send_message(f"❌ You are already in a High queue!", ephemeral=True)
                return

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value.strip(),
            'region': self.region.value.upper().strip(),
            'joined_at': datetime.datetime.utcnow()
        }

        high_queues[self.gamemode].append(player_data)
        guild = interaction.guild

        waitlist_channel = discord.utils.get(guild.text_channels, name=f"high-waitlist-{self.gamemode.lower()}")
        if waitlist_channel:
            await waitlist_channel.set_permissions(interaction.user, read_messages=True, send_messages=False)

        await update_high_board_message(guild, self.gamemode)

# --- MODALE RISULTATO TEST STANDARD ---
class StandardResultModal(discord.ui.Modal):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id, region):
        super().__init__(title=f"Standard Tier Test - {gamemode}")
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.region = region

        current_rank = get_current_rank(player_member, gamemode)

        self.prev_rank = discord.ui.TextInput(
            label="Previous Rank",
            default=current_rank,
            required=True
        )
        self.new_rank = discord.ui.TextInput(
            label="New Rank Earned (LT5 to LT3)",
            placeholder="Ex: LT3",
            required=True
        )
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        rank_earned = self.new_rank.value.strip().upper()
        prev_rank_val = self.prev_rank.value.strip().upper()

        if rank_earned == "UNRANKED":
            await interaction.response.send_message("❌ A player being tested cannot be Unranked! Please enter a valid earned tier.", ephemeral=True)
            return

        valid, err_msg = is_valid_promotion(prev_rank_val, rank_earned)
        if not valid:
            await interaction.response.send_message(f"❌ {err_msg}", ephemeral=True)
            return

        if rank_earned not in TIER_ORDER or TIER_ORDER.index(rank_earned) > TIER_ORDER.index("LT3"):
            await interaction.response.send_message(f"❌ The rank `{rank_earned}` belongs to High Tiers! Please use the High Tier system.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        skin_url = f"https://render.crafty.gg/3d/bust/{self.mc_name}"

        embed = discord.Embed(color=0x5865f2)
        embed.set_author(name=f"{guild.name}'s Test Results 🏆", icon_url=guild.icon.url if guild.icon else None)
        embed.set_thumbnail(url=skin_url)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Region:", value=self.region, inline=False)
        embed.add_field(name="Username:", value=self.mc_name, inline=False)
        embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=False)
        embed.add_field(name="Rank Earned:", value=rank_earned, inline=False)
        
        target_channel = discord.utils.get(guild.text_channels, name="🏆│results")
        if target_channel:
            msg = await target_channel.send(content=self.player_member.mention, embed=embed)
            for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await msg.add_reaction(emo)
                except Exception: pass

        queues[self.gamemode] = [p for p in queues[self.gamemode] if p['user_id'] != self.player_member.id]
        cooldowns[self.player_member.id] = datetime.datetime.utcnow() + datetime.timedelta(days=7)

        w_chan = discord.utils.get(guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        if w_chan:
            await w_chan.set_permissions(self.player_member, overwrite=None)

        for role in self.player_member.roles:
            if self.gamemode in role.name:
                try: await self.player_member.remove_roles(role)
                except: pass

        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.default())
        if role:
            try: await self.player_member.add_roles(role)
            except: pass

        await update_board_message(guild, self.gamemode)
        
        # AGGIORNA AUTOMATICAMENTE IL FILE JSON PER IL SITO (ULTIMO TIER DATO)
        update_json_file(guild)
        
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

# --- MODALE RISULTATO HIGH TIER TEST ---
class HighTierResultModal(discord.ui.Modal):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id, region):
        super().__init__(title=f"High Tier Match - {gamemode}")
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.region = region

        current_rank = get_current_rank(player_member, gamemode)

        self.prev_rank = discord.ui.TextInput(
            label="Previous Rank",
            default=current_rank,
            required=True
        )
        self.new_rank = discord.ui.TextInput(
            label="New Rank Earned (HT3, LT2...) or LT3 (Fail)",
            placeholder="Ex: HT3 or LT3",
            required=True
        )
        self.match_score = discord.ui.TextInput(
            label="Match Score",
            placeholder="Ex: 4-1",
            required=True
        )

        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)
        self.add_item(self.match_score)

    async def on_submit(self, interaction: discord.Interaction):
        rank_earned = self.new_rank.value.strip().upper()
        prev_rank_val = self.prev_rank.value.strip().upper()
        score_val = self.match_score.value.strip()

        if rank_earned == "UNRANKED":
            await interaction.response.send_message("❌ A player being tested cannot be Unranked! Please enter a valid earned tier.", ephemeral=True)
            return

        allowed_high_result_tiers = ["LT3", "HT3", "LT2", "HT2", "LT1", "HT1"]
        if rank_earned not in allowed_high_result_tiers:
            await interaction.response.send_message("❌ In a High Tier Test, the lowest result you can assign if they fail is **LT3**!", ephemeral=True)
            return

        if prev_rank_val not in TIER_ORDER or TIER_ORDER.index(prev_rank_val) < TIER_ORDER.index("LT3"):
            await interaction.response.send_message(f"❌ The player must be at least **LT3** to participate in a High Tier Test! Current rank: `{prev_rank_val}`.", ephemeral=True)
            return

        valid, err_msg = is_valid_promotion(prev_rank_val, rank_earned)
        if not valid:
            await interaction.response.send_message(f"❌ {err_msg}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        c_idx = TIER_ORDER.index(prev_rank_val) if prev_rank_val in TIER_ORDER else 0
        t_idx = TIER_ORDER.index(rank_earned) if rank_earned in TIER_ORDER else 0

        if t_idx <= c_idx:
            eval_status = "Failed High Tier Evaluation"
            final_rank = prev_rank_val
        else:
            eval_status = "Passed High Tier Evaluation"
            final_rank = rank_earned

        content_msg = f"{self.player_member.mention} - {self.mc_name} - Result: **{final_rank}**\n\n**{eval_status}**\n\n**{final_rank} Fights**\n| {score_val}"
        
        target_channel = discord.utils.get(guild.text_channels, name="🥇│hight-results")
        if target_channel:
            msg = await target_channel.send(content=content_msg)
            for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await msg.add_reaction(emo)
                except Exception: pass

        high_queues[self.gamemode] = [p for p in high_queues[self.gamemode] if p['user_id'] != self.player_member.id]
        cooldowns[self.player_member.id] = datetime.datetime.utcnow() + datetime.timedelta(days=7)

        w_chan = discord.utils.get(guild.text_channels, name=f"high-waitlist-{self.gamemode.lower()}")
        if w_chan:
            await w_chan.set_permissions(self.player_member, overwrite=None)

        if t_idx > c_idx:
            for role in self.player_member.roles:
                if self.gamemode in role.name:
                    try: await self.player_member.remove_roles(role)
                    except: pass

            role_name = f"{rank_earned} {self.gamemode}"
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.default())
            if role:
                try: await self.player_member.add_roles(role)
                except: pass

        await update_high_board_message(guild, self.gamemode)
        
        # AGGIORNA AUTOMATICAMENTE IL FILE JSON PER IL SITO (ULTIMO TIER DATO)
        update_json_file(guild)
        
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

# --- VIEWS PANNELLO PRINCIPALE (NORMALE) ---
class MainPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for gm, emoji in GAMEMODE_EMOJIS.items():
            self.add_item(MainPanelButton(gm, emoji))

class MainPanelButton(discord.ui.Button):
    def __init__(self, gamemode: str, emoji: str):
        super().__init__(style=discord.ButtonStyle.secondary, label=gamemode, emoji=emoji, custom_id=f"panel_{gamemode}")
        self.gamemode = gamemode

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.gamemode))

# --- VIEWS PANNELLO PRINCIPALE (HIGH TIERS) ---
class HighMainPanelView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        for gm, emoji in GAMEMODE_EMOJIS.items():
            self.add_item(HighMainPanelButton(gm, emoji))

class HighMainPanelButton(discord.ui.Button):
    def __init__(self, gamemode: str, emoji: str):
        super().__init__(style=discord.ButtonStyle.secondary, label=gamemode, emoji=emoji, custom_id=f"high_panel_{gamemode}")
        self.gamemode = gamemode

    async def callback(self, interaction: discord.Interaction):
        current_rank = get_current_rank(interaction.user, self.gamemode)
        if current_rank not in HIGH_TIERS_QUEUE:
            await interaction.response.send_message(f"❌ You must be at least **LT3** in `{self.gamemode}` to use this panel!", ephemeral=True)
            return
        await interaction.response.send_modal(HighMinecraftNameModal(self.gamemode))

# --- VIEW CONTROLLO WAITLIST NORMALE ---
class StaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.join_tester_btn.custom_id = f"join_t_{gamemode}"
        self.next_player_btn.custom_id = f"next_p_{gamemode}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        tester_role_name = f"Tester {self.gamemode}"
        has_role = any(role.name == tester_role_name for role in interaction.user.roles)
        if not (has_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message(f"❌ You must be a **Tester {self.gamemode}** to use these controls.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple)
    async def join_tester_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_testers[self.gamemode] = interaction.user.id
        await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ The queue is empty!", ephemeral=True)
            return

        current_player = queues[self.gamemode][0]
        guild = interaction.guild
        player_member = guild.get_member(current_player['user_id'])
        
        if not player_member:
            queues[self.gamemode].pop(0)
            await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)
            return

        await interaction.response.defer(ephemeral=True)
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME) or await guild.create_category(CATEGORY_NAME)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        match_room = await guild.create_text_channel(
            name=f"match-{player_member.name}-{self.gamemode.lower()}",
            category=category,
            overwrites=overwrites
        )

        eval_view = TesterPrivateEvalView(player_member, current_player['mc_name'], self.gamemode, match_room.id, current_player['region'], is_high=False)
        
        await match_room.send(content=f"⚡ **Match Room:** {player_member.mention} vs {interaction.user.mention}\n*The match has started! Use the buttons below to assign the result.*", view=eval_view)
        await interaction.message.edit(embed=generate_queue_embed(self.gamemode), view=self)

# --- VIEW CONTROLLO WAITLIST HIGH TIERS ---
class HighStaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.join_tester_btn.custom_id = f"high_join_t_{gamemode}"
        self.next_player_btn.custom_id = f"high_next_p_{gamemode}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        tester_role_name = f"Tester {self.gamemode}"
        has_tester_role = any(role.name == tester_role_name for role in interaction.user.roles)
        current_rank = get_current_rank(interaction.user, self.gamemode)
        has_lt3 = current_rank in HIGH_TIERS_QUEUE

        if interaction.user.guild_permissions.administrator:
            return True

        if not has_tester_role or not has_lt3:
            await interaction.response.send_message(
                f"❌ To join as a High Tester, you must have the **Tester {self.gamemode}** role AND be at least **LT3 {self.gamemode}**! (Your rank: `{current_rank}`)",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple)
    async def join_tester_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_high_testers[self.gamemode] = interaction.user.id
        await interaction.response.edit_message(embed=generate_high_queue_embed(self.gamemode), view=self)

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not high_queues[self.gamemode]:
            await interaction.response.send_message("❌ The High queue is empty!", ephemeral=True)
            return

        current_player = high_queues[self.gamemode][0]
        guild = interaction.guild
        player_member = guild.get_member(current_player['user_id'])
        
        if not player_member:
            high_queues[self.gamemode].pop(0)
            await interaction.response.edit_message(embed=generate_high_queue_embed(self.gamemode), view=self)
            return

        await interaction.response.defer(ephemeral=True)
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME) or await guild.create_category(CATEGORY_NAME)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        match_room = await guild.create_text_channel(
            name=f"high-match-{player_member.name}-{self.gamemode.lower()}",
            category=category,
            overwrites=overwrites
        )

        eval_view = TesterPrivateEvalView(player_member, current_player['mc_name'], self.gamemode, match_room.id, current_player['region'], is_high=True)
        
        await match_room.send(content=f"⚡ **High Match Room:** {player_member.mention} vs {interaction.user.mention}\n*The high tier match has started! Use the button below to assign the result.*", view=eval_view)
        await interaction.message.edit(embed=generate_high_queue_embed(self.gamemode), view=self)

# --- PULSANTI NELLA STANZA MATCH ---
class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id, region, is_high=False):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region = region
        self.is_high = is_high

        if self.is_high:
            self.add_item(discord.ui.Button(label="🔥 HighTierTest Result", style=discord.ButtonStyle.blurple, custom_id="high_eval_btn"))
            for child in self.children:
                if child.custom_id == "high_eval_btn":
                    child.callback = self.high_test_callback
        else:
            self.add_item(discord.ui.Button(label="🟢 TierTest (LT5 - LT3)", style=discord.ButtonStyle.green, custom_id="std_eval_btn"))
            for child in self.children:
                if child.custom_id == "std_eval_btn":
                    child.callback = self.std_test_callback

    async def std_test_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StandardResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region))

    async def high_test_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(HighTierResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region))

# --- GENERAZIONE EMBED WAITLIST ---
def generate_queue_embed(gamemode: str):
    q = queues[gamemode]
    tester_id = active_testers[gamemode]
    
    queue_list = "\n".join([f"`{i+1}.` <@{p['user_id']}>" for i, p in enumerate(q)]) if q else "*Empty*"
    tester_mention = f"<@{tester_id}>" if tester_id else "*None*"

    embed = discord.Embed(
        description=(
            "⏱️ The queue updates instantly.\n"
            "Use `/leave` to exit the waiting list.\n\n"
            f"**__Queue__ ({len(q)}/20):**\n{queue_list}\n\n"
            f"**Active Testers:**\n1. {tester_mention}"
        ),
        color=0x5865f2
    )
    return embed

def generate_high_queue_embed(gamemode: str):
    q = high_queues[gamemode]
    tester_id = active_high_testers[gamemode]
    
    queue_list = "\n".join([f"`{i+1}.` <@{p['user_id']}>" for i, p in enumerate(q)]) if q else "*Empty*"
    tester_mention = f"<@{tester_id}>" if tester_id else "*None*"

    embed = discord.Embed(
        title=f"High Queue - {gamemode} (LT3+ Only)",
        description=(
            "⏱️ The high queue updates instantly.\n"
            "Use `/leave` to exit the waiting list.\n\n"
            f"**__High Queue__ ({len(q)}/20):**\n{queue_list}\n\n"
            f"**Active Testers:**\n1. {tester_mention}"
        ),
        color=0xf1c40f
    )
    return embed

async def update_board_message(guild, gamemode):
    waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{gamemode.lower()}")
    if waitlist_channel:
        async for message in waitlist_channel.history(limit=10):
            if message.author == bot.user:
                await message.edit(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
                break

async def update_high_board_message(guild, gamemode):
    waitlist_channel = discord.utils.get(guild.text_channels, name=f"high-waitlist-{gamemode.lower()}")
    if waitlist_channel:
        async for message in waitlist_channel.history(limit=10):
            if message.author == bot.user:
                await message.edit(embed=generate_high_queue_embed(gamemode), view=HighStaffControlView(gamemode))
                break

# --- COMANDI SLASH ---
@bot.tree.command(name="setup_panel", description="Creates the gamemode selection panel")
async def setup_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.delete_original_response()

    embed = discord.Embed(
        title="Testing Ticket Panel",
        description="Click a gamemode to join the queue!",
        color=0x5865f2
    )
    await interaction.channel.send(embed=embed, view=MainPanelView())

@bot.tree.command(name="setup_high_panel", description="Creates the High Tiers gamemode selection panel (LT3+ only)")
async def setup_high_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.delete_original_response()

    embed = discord.Embed(
        title="High Tiers Testing Panel (LT3+ Required)",
        description="Click a gamemode to join the High queue (Must be LT3+ in that specific gamemode)!",
        color=0xf1c40f
    )
    await interaction.channel.send(embed=embed, view=HighMainPanelView(bot))

@bot.tree.command(name="setup_board", description="Creates the waitlist channel for a gamemode")
@app_commands.describe(gamemode="Name of the gamemode")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return

    if gamemode not in GAMEMODES:
        await interaction.response.send_message(f"❌ Invalid gamemode.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.delete_original_response()

    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME) or await guild.create_category(CATEGORY_NAME)
    
    waitlist_channel = await guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))

@bot.tree.command(name="setup_high_board", description="Creates the High waitlist channel for a gamemode")
@app_commands.describe(gamemode="Name of the gamemode")
async def setup_high_board(interaction: discord.Interaction, gamemode: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can use this command.", ephemeral=True)
        return

    if gamemode not in GAMEMODES:
        await interaction.response.send_message(f"❌ Invalid gamemode.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.delete_original_response()

    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME) or await guild.create_category(CATEGORY_NAME)
    
    waitlist_channel = await guild.create_text_channel(name=f"high-waitlist-{gamemode.lower()}", category=category)
    await waitlist_channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
    await waitlist_channel.send(embed=generate_high_queue_embed(gamemode), view=HighStaffControlView(gamemode))

@bot.tree.command(name="leave", description="Leave your current queue")
async def leave_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    guild = interaction.guild

    for channel in guild.text_channels:
        if (channel.name.startswith("match-") or channel.name.startswith("high-match-")) and str(user_id) in str(channel.overwrites):
            await interaction.response.send_message("❌ You cannot use `/leave` while you are currently in an active match room!", ephemeral=True)
            return

    found = False
    for gm in GAMEMODES:
        q = queues[gm]
        for p in list(q):
            if p['user_id'] == user_id:
                q.remove(p)
                found = True
                waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{gm.lower()}")
                if waitlist_channel:
                    await waitlist_channel.set_permissions(interaction.user, overwrite=None)
                await update_board_message(guild, gm)

        hq = high_queues[gm]
        for p in list(hq):
            if p['user_id'] == user_id:
                hq.remove(p)
                found = True
                waitlist_channel = discord.utils.get(guild.text_channels, name=f"high-waitlist-{gm.lower()}")
                if waitlist_channel:
                    await waitlist_channel.set_permissions(interaction.user, overwrite=None)
                await update_high_board_message(guild, gm)

    if found:
        await interaction.response.send_message("✅ You have been removed from the queue and can no longer see the waitlist channel.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not in any queue.", ephemeral=True)

@bot.tree.command(name="leave_tester", description="Abandon your active tester session for a gamemode")
@app_commands.describe(gamemode="The gamemode")
async def leave_tester_cmd(interaction: discord.Interaction, gamemode: str):
    if gamemode not in GAMEMODES:
        await interaction.response.send_message(f"❌ Invalid gamemode.", ephemeral=True)
        return

    tester_role_name = f"Tester {gamemode}"
    has_role = any(role.name == tester_role_name for role in interaction.user.roles)
    if not (has_role or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message(f"❌ You are not a **Tester {gamemode}**.", ephemeral=True)
        return

    if active_testers[gamemode] != interaction.user.id and active_high_testers[gamemode] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the active tester for this gamemode.", ephemeral=True)
        return

    if active_testers[gamemode] == interaction.user.id:
        active_testers[gamemode] = None
        await update_board_message(interaction.guild, gamemode)
    if active_high_testers[gamemode] == interaction.user.id:
        active_high_testers[gamemode] = None
        await update_high_board_message(interaction.guild, gamemode)

    await interaction.response.send_message(f"✅ You are no longer the active tester for **{gamemode}**.", ephemeral=True)

@bot.tree.command(name="retier", description="Retire a player's Tier rank")
@app_commands.describe(member="The player", gamemode="The gamemode", rank="Current rank to retire")
async def retier_cmd(interaction: discord.Interaction, member: discord.Member, gamemode: str, rank: str):
    tester_role_name = f"Tester {gamemode}"
    has_role = any(role.name == tester_role_name for role in interaction.user.roles)
    if not (has_role or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message(f"❌ You must be a **Tester {gamemode}** to use this command.", ephemeral=True)
        return

    guild = interaction.guild
    old_role_name = f"{rank.upper()} {gamemode}"
    retired_role_name = f"R{rank.upper()} {gamemode}"

    old_role = discord.utils.get(guild.roles, name=old_role_name)
    if old_role and old_role in member.roles:
        await member.remove_roles(old_role)

    retired_role = discord.utils.get(guild.roles, name=retired_role_name)
    if not retired_role:
        retired_role = await guild.create_role(name=retired_role_name, color=discord.Color.light_gray(), mentionable=True)

    await member.add_roles(retired_role)
    
    # Aggiorna il JSON sul sito
    update_json_file(guild)
    
    await interaction.response.send_message(f"✅ **{member.display_name}**'s role updated to `{retired_role_name}`.", ephemeral=True)

@bot.tree.command(name="unretier", description="Restore a player's retired Tier rank")
@app_commands.describe(member="The player", gamemode="The gamemode", rank="Rank to restore")
async def unretier_cmd(interaction: discord.Interaction, member: discord.Member, gamemode: str, rank: str):
    tester_role_name = f"Tester {gamemode}"
    has_role = any(role.name == tester_role_name for role in interaction.user.roles)
    if not (has_role or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message(f"❌ You must be a **Tester {gamemode}** to use this command.", ephemeral=True)
        return

    guild = interaction.guild
    retired_role_name = f"R{rank.upper()} {gamemode}"
    active_role_name = f"{rank.upper()} {gamemode}"

    retired_role = discord.utils.get(guild.roles, name=retired_role_name)
    if retired_role and retired_role in member.roles:
        await member.remove_roles(retired_role)

    active_role = discord.utils.get(guild.roles, name=active_role_name)
    if not active_role:
        active_role = await guild.create_role(name=active_role_name, mentionable=True, color=discord.Color.default())

    await member.add_roles(active_role)
    
    # Aggiorna il JSON sul sito
    update_json_file(guild)
    
    await interaction.response.send_message(f"✅ **{member.display_name}**'s role restored to `{active_role_name}`.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot connected as: {bot.user.name}")
    for gm in GAMEMODES:
        bot.add_view(StaffControlView(gm))
        bot.add_view(HighStaffControlView(gm))
    bot.add_view(MainPanelView())
    bot.add_view(HighMainPanelView(bot))
    if not check_queue_timeouts.is_running():
        check_queue_timeouts.start()
    await bot.tree.sync()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
