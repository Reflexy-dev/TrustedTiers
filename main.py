import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import os

# --- CONFIGURAZIONE BOT ---
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Configurazioni Gamemodes e Emoji
GAMEMODES = {
    "Sword": "⚔️", "Axe": "🪓", "UHC": "🍎", "DiaPot": "💎", 
    "NethPot": "🔥", "DiaSMP": "🛡️", "SMP": "🏡", "SpearMace": "🔱", 
    "Mace": "🔨", "Cart": "🛒", "Crystal": "🔮"
}

# Strutture dati in memoria
queue_data = {gm: [] for gm in GAMEMODES}
active_tests = {}
cooldowns = {}
retiered_users = {}


# --- MODALE PER LA PRENOTAZIONE ---
class BookingModal(discord.ui.Modal):
    def __init__(self, gamemode: str):
        super().__init__(title=f"Book Test: {gamemode}")
        self.gamemode = gamemode

        self.ign = discord.ui.TextInput(
            label="Minecraft Nickname",
            placeholder="Insert your nick...",
            required=True
        )
        self.region = discord.ui.TextInput(
            label="Region",
            placeholder="EU, NA, ASIA...",
            required=True,
            max_length=10
        )
        self.add_item(self.ign)
        self.add_item(self.region)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        now = datetime.datetime.utcnow()

        # Controllo Cooldown (7 giorni) tranne per l'Owner
        if user.id in cooldowns and user.id != interaction.guild.owner_id:
            time_left = cooldowns[user.id] - now
            if time_left.total_seconds() > 0:
                hours = int(time_left.total_seconds() // 3600)
                await interaction.response.send_message(
                    f"❌ You are on cooldown! You must wait another **{hours} hours** before requesting another test.",
                    ephemeral=True
                )
                return

        # Controllo se è già in una coda qualsiasi
        for gm, q in queue_data.items():
            if any(p["user_id"] == user.id for p in q):
                await interaction.response.send_message(
                    "❌ You are already in a queue for a gamemode!", ephemeral=True
                )
                return

        # Controllo se è attualmente in test attivo
        for gm, test in active_tests.items():
            if test.get("player_id") == user.id:
                await interaction.response.send_message(
                    "❌ You are currently involved in an active test!", ephemeral=True
                )
                return

        # Inserimento nella coda
        player_info = {
            "user_id": user.id,
            "ign": self.ign.value,
            "region": self.region.value
        }
        
        queue_data[self.gamemode].append(player_info)
        await update_board_message(interaction.guild, self.gamemode)
        
        await interaction.response.send_message(
            f"✅ Successfully joined the **{self.gamemode}** queue! Position: `{len(queue_data[self.gamemode])}`",
            ephemeral=True
        )


# --- VIEW PER LA BOARD PRINCIPALE ---
class BoardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for gm, emoji in GAMEMODES.items():
            self.add_item(BoardButton(gm, emoji))

class BoardButton(discord.ui.Button):
    def __init__(self, gamemode: str, emoji: str):
        super().__init__(style=discord.ButtonStyle.secondary, label=gamemode, emoji=emoji, custom_id=f"board_{gamemode}")
        self.gamemode = gamemode

    async def callback(self, interaction: discord.Interaction):
        modal = BookingModal(self.gamemode)
        await interaction.response.send_modal(modal)


# --- VIEW DELLA WAITLIST (CON BOTTONE TESTER) ---
class WaitlistControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.add_item(NextPlayerButton(gamemode))
        self.add_item(JoinAsTesterButton(gamemode))

class NextPlayerButton(discord.ui.Button):
    def __init__(self, gamemode: str):
        super().__init__(style=discord.ButtonStyle.success, label="Next", custom_id=f"next_{gamemode}")
        self.gamemode = gamemode

    async def callback(self, interaction: discord.Interaction):
        tester_role_name = f"Tester {self.gamemode}"
        is_tester = any(r.name == tester_role_name for r in interaction.user.roles)
        is_owner = (interaction.user.id == interaction.guild.owner_id)

        if not is_tester and not is_owner:
            await interaction.response.send_message("❌ Only the assigned testers for this gamemode can use this button.", ephemeral=True)
            return

        if not queue_data[self.gamemode]:
            await interaction.response.send_message("❌ The queue is empty!", ephemeral=True)
            return

        player_data = queue_data[self.gamemode].pop(0)
        await update_board_message(interaction.guild, self.gamemode)

        player = interaction.guild.get_member(player_data["user_id"])
        if not player:
            await interaction.response.send_message("❌ Player left the server.", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        category = interaction.channel.category
        test_channel = await interaction.guild.create_text_channel(
            name=f"test-{player.name}-{self.gamemode.lower()}",
            category=category,
            overwrites=overwrites
        )

        active_tests[self.gamemode] = {
            "tester_id": interaction.user.id,
            "player_id": player.id,
            "channel_id": test_channel.id,
            "player_ign": player_data["ign"]
        }

        finish_view = FinishTestView(self.gamemode, player)
        await test_channel.send(
            f"⚔️ Test started between <@{interaction.user.id}> and <@{player.id}>!\n"
            f"**IGN:** `{player_data['ign']}` | **Region:** `{player_data['region']}`\n"
            f"Click the button below when the test is completed to assign the tier.",
            view=finish_view
        )

        await interaction.response.send_message(f"✅ Test started in {test_channel.mention}!", ephemeral=True)


class JoinAsTesterButton(discord.ui.Button):
    def __init__(self, gamemode: str):
        super().__init__(style=discord.ButtonStyle.primary, label="Join as Tester", custom_id=f"jointester_{gamemode}")
        self.gamemode = gamemode

    async def callback(self, interaction: discord.Interaction):
        role_name = f"Tester {self.gamemode}"
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(name=role_name, color=discord.Color.blue())

        await interaction.user.add_roles(role)
        await interaction.response.send_message(f"✅ You have joined as a tester for **{self.gamemode}**!", ephemeral=True)


# --- MODALE PER LA CONCLUSIONE DEL TEST E ASSEGNAZIONE TIER ---
class FinishTestModal(discord.ui.Modal):
    def __init__(self, gamemode: str, player: discord.Member):
        super().__init__(title=f"Assign Tier - {gamemode}")
        self.gamemode = gamemode
        self.player = player

        self.old_tier = discord.ui.TextInput(
            label="Previous Tier",
            placeholder="Type 'Unranked' if none...",
            required=True
        )
        self.new_tier = discord.ui.TextInput(
            label="New Tier (e.g. HT3, LT1, HT5...)",
            placeholder="Insert new tier...",
            required=True
        )
        self.score = discord.ui.TextInput(
            label="Match Score (If HT3 or above)",
            placeholder="e.g. 4-1 (Leave blank if below HT3)",
            required=False
        )

        self.add_item(self.old_tier)
        self.add_item(self.new_tier)
        self.add_item(self.score)

    async def on_submit(self, interaction: discord.Interaction):
        nt = self.new_tier.value.strip().upper()
        ot = self.old_tier.value.strip()
        match_score = self.score.value.strip()

        is_high_tier = ("HT3" in nt or "HT2" in nt or "HT1" in nt)
        if is_high_tier and not match_score:
            await interaction.response.send_message("❌ Since this is HT3 or above, you must specify the match score!", ephemeral=True)
            return

        formatted_tier_name = f"{nt} {self.gamemode}"
        guild = interaction.guild
        
        role = discord.utils.get(guild.roles, name=formatted_tier_name)
        if not role:
            role = await guild.create_role(
                name=formatted_tier_name,
                color=discord.Color.from_rgb(255, 255, 255),
                hoist=True
            )
        
        for r in self.player.roles:
            if self.gamemode in r.name and r.name != formatted_tier_name:
                try:
                    await self.player.remove_roles(r)
                except:
                    pass
        await self.player.add_roles(role)

        cooldowns[self.player.id] = datetime.datetime.utcnow() + datetime.timedelta(days=7)

        if self.gamemode in active_tests:
            del active_tests[self.gamemode]

        results_channel = discord.utils.get(guild.text_channels, name="🏆│results")
        if results_channel:
            player_ign = self.player.display_name
            skin_url = f"https://render.crafty.gg/3d/bust/{player_ign}"

            embed = discord.Embed(
                title=f"Tier Test Result - {self.gamemode}",
                color=discord.Color.from_rgb(255, 255, 255),
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=skin_url)
            embed.add_field(name="Player", value=f"{self.player.mention} (`{player_ign}`)", inline=False)
            embed.add_field(name="Old Tier", value=ot, inline=True)
            embed.add_field(name="New Tier", value=formatted_tier_name, inline=True)
            
            if is_high_tier and match_score:
                embed.add_field(name="Match Score", value=match_score, inline=False)

            await results_channel.send(embed=embed)

        await interaction.response.send_message("✅ Test finalized successfully! Results posted.", ephemeral=True)

        channel = interaction.channel
        await asyncio.sleep(5)
        await channel.delete()


class FinishTestView(discord.ui.View):
    def __init__(self, gamemode: str, player: discord.Member):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.player = player

    @discord.ui.button(label="Complete & Assign Tier", style=discord.ButtonStyle.danger, custom_id="complete_test_btn")
    async def complete_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = FinishTestModal(self.gamemode, self.player)
        await interaction.response.send_modal(modal)


# --- FUNZIONE AGGIORNAMENTO BOARD VISIVA ---
async def update_board_message(guild: discord.guild, gamemode: str):
    channel_name = f"waitlist-{gamemode.lower()}"
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        return

    q = queue_data[gamemode]
    queue_list_str = "\n".join([f"`{i+1}.` {p['ign']} ({p['region']})" for i, p in enumerate(q)]) if q else "Queue is empty."

    embed = discord.Embed(
        title=f"Waitlist - {gamemode}",
        description=f"**Current Queue (Max 20):**\n{queue_list_str}",
        color=discord.Color.blue()
    )
    
    async for message in channel.history(limit=10):
        if message.author == bot.user:
            await message.edit(embed=embed, view=WaitlistControlView(gamemode))
            return
            
    await channel.send(embed=embed, view=WaitlistControlView(gamemode))


# --- COMANDI SLASH ---

@bot.tree.command(name="setup_board", description="Create the main booking board or specific gamemode waitlist")
@app_commands.describe(nome_gamemode="The gamemode name or type 'main' for the request channel")
async def setup_board(interaction: discord.Interaction, nome_gamemode: str):
    if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ You do not have permissions to use this command.", ephemeral=True)
        return

    guild = interaction.guild

    if nome_gamemode.lower() == "main":
        await interaction.response.send_message("✅ Main board created here!", ephemeral=True)
        embed = discord.Embed(
            title="Tier Test Booking",
            description="Click a gamemode button below to book your test!",
            color=discord.Color.gold()
        )
        await interaction.channel.send(embed=embed, view=BoardView())
    else:
        if nome_gamemode not in GAMEMODES:
            await interaction.response.send_message(f"❌ Invalid gamemode. Choose from: {list(GAMEMODES.keys())}", ephemeral=True)
            return

        ch_name = f"waitlist-{nome_gamemode.lower()}"
        existing_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not existing_ch:
            existing_ch = await guild.create_text_channel(name=ch_name)

        await interaction.response.send_message(f"✅ Waitlist channel created: {existing_ch.mention}", ephemeral=True)
        await update_board_message(guild, nome_gamemode)


@bot.tree.command(name="leave", description="Leave the active queue or tester mode")
async def leave(interaction: discord.Interaction):
    user_id = interaction.user.id
    removed = False

    for gm, q in queue_data.items():
        for p in q:
            if p["user_id"] == user_id:
                q.remove(p)
                removed = True
                await update_board_message(interaction.guild, gm)

    if removed:
        await interaction.response.send_message("✅ You have been removed from the queue.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not in any queue.", ephemeral=True)


@bot.tree.command(name="kickqueue", description="Remove a player from the queue")
@app_commands.describe(nome_player="The Minecraft IGN or Discord mention")
async def kickqueue(interaction: discord.Interaction, nome_player: str):
    is_tester = any("Tester" in r.name for r in interaction.user.roles)
    if not is_tester and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Only testers can use this command.", ephemeral=True)
        return

    removed = False
    for gm, q in queue_data.items():
        for p in q[:]:
            if p["ign"].lower() == nome_player.lower():
                q.remove(p)
                removed = True
                await update_board_message(interaction.guild, gm)

    if removed:
        await interaction.response.send_message(f"✅ Player `{nome_player}` has been kicked from the queue.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Player `{nome_player}` not found in any queue.", ephemeral=True)


@bot.tree.command(name="retier", description="Retire from a gamemode tier, moving to RHT format")
@app_commands.describe(nome_gamemode="The gamemode name")
async def retier(interaction: discord.Interaction, nome_gamemode: str):
    if nome_gamemode not in GAMEMODES:
        await interaction.response.send_message("❌ Invalid gamemode.", ephemeral=True)
        return

    user = interaction.user
    gray_role = discord.utils.get(interaction.guild.roles, name=f"RHT5 {nome_gamemode}")
    if not gray_role:
        gray_role = await interaction.guild.create_role(
            name=f"RHT5 {nome_gamemode}",
            color=discord.Color.from_rgb(128, 128, 128),
            hoist=True
        )

    for r in user.roles:
        if nome_gamemode in r.name:
            try:
                await user.remove_roles(r)
            except:
                pass

    await user.add_roles(gray_role)
    if user.id not in retiered_users:
        retiered_users[user.id] = {}
    retiered_users[user.id][nome_gamemode] = True

    await interaction.response.send_message(f"✅ You have successfully retired in **{nome_gamemode}**. Role updated to gray.", ephemeral=True)


@bot.tree.command(name="unretier", description="Undo your retirement after 35 days")
@app_commands.describe(nome_gamemode="The gamemode name")
async def unretier(interaction: discord.Interaction, nome_gamemode: str):
    user_id = interaction.user.id
    if user_id in retiered_users and nome_gamemode in retiered_users[user_id]:
        del retiered_users[user_id][nome_gamemode]
        await interaction.response.send_message(f"✅ Successfully un-retired from **{nome_gamemode}**! Your status has been restored.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ You are not marked as retired in this gamemode.", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)


# --- AVVIO DEL BOT CON RENDER ENV VAR ---
TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN is None:
    print("❌ ERRORE: Nessun token trovato nelle variabili d'ambiente di Render (DISCORD_TOKEN)!")
else:
    bot.run(TOKEN)
