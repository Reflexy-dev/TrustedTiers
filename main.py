import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import os
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
active_testers = {gm: None for gm in GAMEMODES}
cooldowns = {}
CATEGORY_NAME = "🎯Tierlist"

TIER_ORDER = [
    "Unranked", "LT5", "HT5", "LT4", "HT4", "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"
]

HIGH_TIERS = ["HT3", "LT2", "HT2", "LT1", "HT1"]

def get_current_rank(member: discord.Member, gamemode: str) -> str:
    for role in member.roles:
        for t in TIER_ORDER:
            if role.name == f"{t} {gamemode}":
                return t
    return "Unranked"

def is_valid_promotion(current_rank: str, target_rank: str) -> (bool, str):
    c_rank = current_rank.upper().strip()
    t_rank = target_rank.upper().strip()

    if c_rank not in TIER_ORDER or t_rank not in TIER_ORDER:
        return True, ""

    c_idx = TIER_ORDER.index(c_rank)
    t_idx = TIER_ORDER.index(t_rank)

    if c_rank in HIGH_TIERS and t_idx <= c_idx:
        return False, f"High Tier rule: If you fail or match your current tier (`{c_rank}`), you stay at your current rank!"

    if t_idx > c_idx + 1:
        next_step = TIER_ORDER[c_idx + 1]
        return False, f"Invalid progression! The player is `{c_rank}` and can only advance to the next rank (`{next_step}`). They cannot skip directly to `{t_rank}`!"

    return True, ""


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
            else:
                new_queue.append(player)
        
        if updated:
            queues[gm] = new_queue
            for guild in bot.guilds:
                await update_board_message(guild, gm)

@check_queue_timeouts.before_loop
async def before_timeouts():
    await bot.wait_until_ready()


# --- MODALE INSERIMENTO NICK MINECRAFT (SENZA MESSAGGIO VISIBILE) ---
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

        if len(queues[self.gamemode]) >= 20:
            await interaction.response.send_message("❌ The queue for this gamemode is full (max 20)!", ephemeral=True)
            return

        for gm, q in queues.items():
            if any(p['user_id'] == user_id for p in q):
                await interaction.response.send_message(f"❌ You are already in a queue!", ephemeral=True)
                return

        # Rimuove istantaneamente qualsiasi messaggio di risposta dell'interazione
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
        await update_board_message(interaction.guild, self.gamemode)


# --- MODALE RISULTATO TEST STANDARD (LT5, HT5, LT4, HT4, LT3) ---
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
            label="New Rank Earned (LT5, HT5, LT4, HT4, LT3)",
            placeholder="Ex: LT4",
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

        if rank_earned in HIGH_TIERS:
            await interaction.response.send_message(f"❌ The rank `{rank_earned}` belongs to High Tiers! Please use the **HighTierTest** button.", ephemeral=True)
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

        content_msg = f"{self.player_member.mention} - {self.mc_name} - Promoted to **{rank_earned}**\n\n**Passed High Tier Evaluation**\n\n**{rank_earned} Fights**\n| {score_val}"
        target_channel = discord.utils.get(guild.text_channels, name="🥇│hight-results")
        if target_channel:
            msg = await target_channel.send(content=content_msg)
            for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await msg.add_reaction(emo)
                except Exception: pass

        queues[self.gamemode] = [p for p in queues[self.gamemode] if p['user_id'] != self.player_member.id]
        cooldowns[self.player_member.id] = datetime.datetime.utcnow() + datetime.timedelta(days=7)

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
        
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass


# --- VIEW PANNELLO PRINCIPALE ---
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


# --- VIEW CONTROLLO WAITLIST ---
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
        role_name = f"Tester {self.gamemode}"
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(name=role_name, color=discord.Color.blue())
        await interaction.user.add_roles(role)
        
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

        eval_view = TesterPrivateEvalView(player_member, current_player['mc_name'], self.gamemode, match_room.id, current_player['region'])
        
        await match_room.send(content=f"⚡ **Match Room:** {player_member.mention} vs {interaction.user.mention}\n*The match has started! Use the buttons below to assign the result.*", view=eval_view)
        await interaction.message.edit(embed=generate_queue_embed(self.gamemode), view=self)


# --- 2 PULSANTI NELLA STANZA MATCH ---
class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id, region):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region = region

    @discord.ui.button(label="🟢 TierTest (LT5 - LT3)", style=discord.ButtonStyle.green)
    async def standard_test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StandardResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region))

    @discord.ui.button(label="🔥 HighTierTest (HT3 - HT1)", style=discord.ButtonStyle.blurple)
    async def high_tier_test_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
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


async def update_board_message(guild, gamemode):
    waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{gamemode.lower()}")
    if waitlist_channel:
        async for message in waitlist_channel.history(limit=10):
            if message.author == bot.user:
                await message.edit(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
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
    
    await waitlist_channel.set_permissions(guild.default_role, read_messages=True, send_messages=False)
    
    tester_role = discord.utils.get(guild.roles, name=f"Tester {gamemode}")
    if tester_role:
        await waitlist_channel.set_permissions(tester_role, read_messages=True, send_messages=False)

    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))


@bot.tree.command(name="leave", description="Leave your current queue")
async def leave_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id

    for channel in interaction.guild.text_channels:
        if channel.name.startswith("match-") and str(user_id) in str(channel.overwrites):
            await interaction.response.send_message("❌ You cannot use `/leave` while you are currently in an active match room!", ephemeral=True)
            return

    found = False
    for gm in GAMEMODES:
        q = queues[gm]
        for p in list(q):
            if p['user_id'] == user_id:
                q.remove(p)
                found = True
                await update_board_message(interaction.guild, gm)

    if found:
        await interaction.response.send_message("✅ You have been removed from the queue.", ephemeral=True)
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

    if active_testers[gamemode] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the active tester for this gamemode.", ephemeral=True)
        return

    active_testers[gamemode] = None
    await update_board_message(interaction.guild, gamemode)
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
    await interaction.response.send_message(f"✅ **{member.display_name}**'s role restored to `{active_role_name}`.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Bot connected as: {bot.user.name}")
    for gm in GAMEMODES:
        bot.add_view(StaffControlView(gm))
    bot.add_view(MainPanelView())
    if not check_queue_timeouts.is_running():
        check_queue_timeouts.start()
    await bot.tree.sync()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
