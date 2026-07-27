import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import os
import aiohttp
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
retirements = {}
CATEGORY_NAME = "🎯Tierlist"


def is_high_tier(rank_earned: str) -> bool:
    rank_lower = rank_earned.lower()
    high_keywords = ["lt1", "ht1", "lt2", "ht2", "ht3", "tier 1", "tier 2", "tier 3"]
    if any(k in rank_lower for k in high_keywords):
        if "ht3" in rank_lower or "tier 3" in rank_lower:
            return "high" in rank_lower or "ht3" in rank_lower
        return True
    return False


# --- MODALE INSERIMENTO NICK MINECRAFT ---
class MinecraftNameModal(discord.ui.Modal):
    def __init__(self, gamemode: str):
        super().__init__(title=f"Queue: {gamemode}")
        self.gamemode = gamemode

        self.mc_name = discord.ui.TextInput(
            label="Minecraft Username",
            placeholder="ex: Steve...",
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
            await interaction.response.send_message("❌ Queue is full (Max 20)!", ephemeral=True)
            return

        for gm, q in queues.items():
            if any(p['user_id'] == user_id for p in q):
                await interaction.response.send_message("❌ You are already in a queue!", ephemeral=True)
                return

        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value.strip(),
            'region': self.region.value.upper().strip()
        }

        queues[self.gamemode].append(player_data)
        await update_board_message(interaction.guild, self.gamemode)
        
        await interaction.response.send_message(
            f"✅ Successfully joined the **{self.gamemode}** queue!", ephemeral=True
        )


# --- MODALE VALUTAZIONE FINALE (SOLO 2 CAMPI INIZIALI + MATCH SCORE SE HT3+) ---
class FastResultModal(discord.ui.Modal):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id, region):
        super().__init__(title=f"Assign Tier - {gamemode}")
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        self.region = region

        self.prev_rank = discord.ui.TextInput(
            label="Previous Rank",
            placeholder="Unranked",
            default="Unranked",
            required=True
        )
        self.new_rank = discord.ui.TextInput(
            label="New Rank Earned",
            placeholder="e.g. LT4, HT3, HT1...",
            required=True
        )
        self.match_score = discord.ui.TextInput(
            label="Match Score (Only if HT3 or above)",
            placeholder="e.g. Won 4-1 vs. opponent",
            required=False
        )

        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)
        self.add_item(self.match_score)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        prev_rank_val = self.prev_rank.value.strip() or "Unranked"
        score_val = self.match_score.value.strip()

        is_high = is_high_tier(rank_earned)
        if is_high and not score_val:
            await interaction.followup.send("❌ You must specify the match score for HT3 or above!", ephemeral=True)
            return

        # Recupero skin corretta da Minecraft tramite Crafty.gg
        skin_url = f"https://render.crafty.gg/3d/bust/{self.mc_name}"

        if is_high:
            content_msg = f"{self.player_member.mention} - {self.mc_name} - Promoted to **{rank_earned}**\n\n**Passed Evaluation**\n\n**{rank_earned} Fights**\n| {score_val}"
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
            embed.add_field(name="Username:", value=self.mc_name, inline=False)
            embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=False)
            embed.add_field(name="Rank Earned:", value=rank_earned, inline=False)
            
            target_channel = discord.utils.get(guild.text_channels, name="🏆│results")
            if target_channel:
                msg = await target_channel.send(content=self.player_member.mention, embed=embed)
                for emo in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                    try: await msg.add_reaction(emo)
                    except Exception: pass

        # Pulizia coda e assegnazione ruolo
        queues[self.gamemode] = [p for p in queues[self.gamemode] if p['user_id'] != self.player_member.id]
        cooldowns[self.player_member.id] = datetime.datetime.utcnow() + datetime.timedelta(days=35)

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
        
        # ELIMINA COMPLETAMENTE IL CANALE PRIVATO DEL MATCH
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass


# --- VIEW PER IL PANNELLO PRINCIPALE ORDINATO A GRIGLIA ---
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


# --- VIEW CONTROLLO WAITLIST (VISIBILE SOLO AI TESTER) ---
class StaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.join_tester_btn.custom_id = f"join_t_{gamemode}"
        self.next_player_btn.custom_id = f"next_p_{gamemode}"
        self.leave_session_btn.custom_id = f"leave_s_{gamemode}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        if not (has_role or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Only testers can use these controls.", ephemeral=True)
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
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        match_room = await guild.create_text_channel(
            name=f"match-{player_member.name}-{self.gamemode.lower()}",
            category=category,
            overwrites=overwrites
        )

        eval_view = TesterPrivateEvalView(player_member, current_player['mc_name'], self.gamemode, match_room.id, current_player['region'])
        await match_room.send(content=f"⚡ **Match Room:** {player_member.mention} vs {interaction.user.mention}", view=eval_view)
        await interaction.message.edit(embed=generate_queue_embed(self.gamemode), view=self)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_testers[self.gamemode] = None
        await interaction.response.edit_message(embed=generate_queue_embed(self.gamemode), view=self)


class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id, region):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id
        self.region = region

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green)
    async def open_eval(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FastResultModal(self.player_member, self.mc_name, self.gamemode, self.channel_id, self.region))


# --- GENERAZIONE EMBED WAITLIST ---
def generate_queue_embed(gamemode: str):
    q = queues[gamemode]
    tester_id = active_testers[gamemode]
    
    title_status = "🟢 Tester(s) Available!" if tester_id else "⚪ Waiting for Tester(s)..."
    queue_list = "\n".join([f"`{i+1}.` <@{p['user_id']}> ({p['region']})" for i, p in enumerate(q)]) if q else "*Empty*"
    tester_mention = f"<@{tester_id}>" if tester_id else "*None*"

    embed = discord.Embed(
        title=title_status,
        description=(
            "⚪ The queue updates automatically.\n"
            "Use `/leave` if you wish to be removed from the waitlist or queue.\n\n"
            f"**__Queue__ ({len(q)}/20):**\n{queue_list}\n\n"
            f"**Active Testers:**\n{tester_mention}"
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

@bot.tree.command(name="setup_panel", description="Create the main permanent gamemode selection panel")
async def setup_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Tier Test Booking Panel",
        description="Click a gamemode below to request a test!",
        color=0x5865f2
    )
    await interaction.response.send_message(embed=embed, view=MainPanelView())


@bot.tree.command(name="setup_board", description="Create the waitlist channel inside 🎯Tierlist category")
@app_commands.describe(gamemode="The gamemode name")
async def setup_board(interaction: discord.Interaction, gamemode: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    if gamemode not in GAMEMODES:
        await interaction.response.send_message(f"❌ Invalid gamemode.", ephemeral=True)
        return

    guild = interaction.guild
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME) or await guild.create_category(CATEGORY_NAME)
    
    waitlist_channel = await guild.create_text_channel(name=f"waitlist-{gamemode.lower()}", category=category)
    
    # Rendi la waitlist invisibile ai player comuni se vuoi che la vedano solo i tester, oppure gestisci i permessi
    await waitlist_channel.set_permissions(guild.default_role, read_messages=False)
    tester_role = discord.utils.get(guild.roles, name=f"Tester {gamemode}")
    if tester_role:
        await waitlist_channel.set_permissions(tester_role, read_messages=True, send_messages=True)

    await waitlist_channel.send(embed=generate_queue_embed(gamemode), view=StaffControlView(gamemode))
    await interaction.response.send_message(f"✅ Waitlist created for **{gamemode}**!", ephemeral=True)


@bot.tree.command(name="leave", description="Leave your current queue or waitlist")
async def leave_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    found = False
    for gm in GAMEMODES:
        q = queues[gm]
        for p in q:
            if p['user_id'] == user_id:
                q.remove(p)
                found = True
                await update_board_message(interaction.guild, gm)

    if found:
        await interaction.response.send_message("✅ You have been removed from the queue.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not in any queue.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    for gm in GAMEMODES:
        bot.add_view(StaffControlView(gm))
    bot.add_view(MainPanelView())
    await bot.tree.sync()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
