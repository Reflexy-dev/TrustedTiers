import discord
from discord.ext import commands
from discord import app_commands
import os
from flask import Flask
from threading import Thread
import asyncio

# --- CONFIGURAZIONE FLASK PER KEEP-ALIVE (Render + UptimeRobot) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is online!"

def run():
    # Render assegna una porta dinamica tramite variabile d'ambiente, altrimenti usa 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- CONFIGURAZIONE DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Dizionario delle Gamemode associate alle rispettive Emoji
GAMEMODE_EMOJIS = {
    "Sword": "⚔️",
    "Axe": "🪓",
    "UHC": "🍎",
    "DiaPot": "💎",
    "NethPot": "🔥",
    "DiaSMP": "🛡️",
    "SMP": "🏡",
    "SpearMace": "🔱",
    "Mace": "🔨",
    "Cart": "🛒",
    "Crystal": "🔮"
}

GAMEMODES = list(GAMEMODE_EMOJIS.keys())
queues = {gm: [] for gm in GAMEMODES}

class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Enter your Minecraft Username", placeholder="e.g. Stev3_", required=True)
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=False),
        }
        
        tester_role = discord.utils.get(guild.roles, name="Tester")
        if tester_role:
            overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"⏳-wait-{self.gamemode.lower()}-{interaction.user.name}"
        ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
        
        player_data = {
            'user_id': interaction.user.id,
            'mc_name': self.mc_name.value,
            'ticket_channel_id': ticket_channel.id
        }
        queues[self.gamemode].append(player_data)
        pos = len(queues[self.gamemode])

        emoji = GAMEMODE_EMOJIS.get(self.gamemode, "❓")
        embed = discord.Embed(
            title=f"{emoji} Queue for {self.gamemode}",
            description=f"Hello {interaction.user.mention}, you have been added to the queue.\n\n"
                        f"**Minecraft Username:** `{self.mc_name.value}`\n"
                        f"**Your Position:** #{pos}\n\n"
                        f"Please wait until a **Tester** starts your session. Your chat access is currently locked.",
            color=discord.Color.orange()
        )
        
        view = TesterControlView(self.gamemode, player_data)
        await ticket_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"Ticket created! Check {ticket_channel.mention}", ephemeral=True)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm], description=f"Queue for {gm} test") 
            for gm in GAMEMODES
        ]
        super().__init__(placeholder="Choose a Gamemode to test...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values[0]))

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

class TesterControlView(discord.ui.View):
    def __init__(self, gamemode, player_data):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.player_data = player_data

    @discord.ui.button(label="Start Test", style=discord.ButtonStyle.green)
    async def start_test(self, interaction: discord.Interaction):
        # 1. RISOLTO ERRORE INTERAZIONE: Diciamo subito a Discord di attendere l'elaborazione
        await interaction.response.defer()

        # 2. RISOLTO CONTROLLO RUOLI: Verifica se l'utente è Owner, Amministratore o ha i ruoli specificati
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        is_tester = any(role.name == "Tester" for role in interaction.user.roles)
        is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)

        if not (is_owner_guild or is_admin or is_tester or is_owner_role):
            await interaction.followup.send("❌ Solo i Tester o gli Owner scritti nei ruoli possono avviare questo test!", ephemeral=True)
            return

        channel = interaction.channel
        guild = interaction.guild
        player = guild.get_member(self.player_data['user_id'])
        
        if player:
            await channel.set_permissions(player, read_messages=True, send_messages=True)
            emoji = GAMEMODE_EMOJIS.get(self.gamemode, "")
            await channel.edit(name=f"🟢-test-{self.gamemode.lower()}-{player.name}")
            
            if self.player_data in queues[self.gamemode]:
                queues[self.gamemode].remove(self.player_data)
                
            await interaction.followup.send(
                f"🟢 Test iniziato! {player.mention} adesso puoi scrivere in chat.\n"
                f"Modalità: **Test {emoji} {self.gamemode}**\n"
                f"Usa `/result` per pubblicare il punteggio finale e `/next_tier` quando hai finito per chiudere il ticket."
            )
        else:
            await interaction.followup.send("Il giocatore ha abbandonato il server Discord.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)

@bot.command()
@commands.is_owner()
async def setup_queue(ctx):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select the gamemode you want to be tested in from the dropdown menu below.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MainTicketView())

@bot.tree.command(name="result", description="Submit a tierlist test result")
@app_commands.describe(
    player="The Discord user tested",
    minecraft_name="Their Minecraft username",
    gamemode="The gamemode tested",
    result_score="The score (e.g. 2-1, 3-0)",
    previous_rank="Their old tier (or Unranked)",
    rank_earned="The new tier earned (e.g. LT4, HT2, LT1)"
)
async def result(
    interaction: discord.Interaction, 
    player: discord.Member, 
    minecraft_name: str,
    gamemode: str,
    result_score: str,
    previous_rank: str,
    rank_earned: str
):
    # Controllo permessi anche per il comando dei risultati
    is_tester = any(role.name == "Tester" for role in interaction.user.roles)
    is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if not (is_tester or is_owner_role or is_admin):
        await interaction.response.send_message("❌ Devi avere il ruolo Tester o Owner per usare questo comando.", ephemeral=True)
        return

    await interaction.response.defer()

    # 3. RISOLTO SKIN URL: Corretto l'indirizzo dell'API di Crafatar per mostrare il render 3D completo
    skin_url = f"https://crafatar.com{minecraft_name}?overlay"

    emoji = GAMEMODE_EMOJIS.get(gamemode, "🏆")
    embed = discord.Embed(color=0x2f3136)
    embed.set_author(name=f"Risultati Test di {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    
    embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
    embed.add_field(name="Gamemode:", value=f"{emoji} `{gamemode}` (Punteggio: {result_score})", inline=False)
    embed.add_field(name="Username MC:", value=f"*{minecraft_name}* ({player.mention})", inline=False)
    embed.add_field(name="Tier Precedente:", value=previous_rank, inline=True)
    embed.add_field(name="Nuovo Tier Guadagnato:", value=f"**{rank_earned}**", inline=True)
    
    # Imposta l'immagine della skin sul lato destro dell'embed
    embed.set_thumbnail(url=skin_url)

    msg = await interaction.followup.send(embed=embed)
    
    reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
    for emo in reactions:
        await msg.add_reaction(emo)

    # --- ASSEGNAZIONE RUOLO DISCORD AUTOMATICA ---
    role_name = f"{rank_earned} {gamemode}"
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=role_name)
    
    if not role:
        try:
            role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            await interaction.channel.send(f"⚠️ Il ruolo `{role_name}` non esisteva. L'ho creato automaticamente.")
        except Exception as e:
            await interaction.channel.send(f"❌ Impossibile creare il ruolo `{role_name}`: {e}")

    if role:
        try:
            await player.add_roles(role)
            await interaction.channel.send(f"✅ Ruolo {role.mention} assegnato automaticamente a {player.mention}!")
        except Exception as e:
            await interaction.channel.send(f"❌ Impossibile assegnare il ruolo. Verifica che il ruolo del bot sia posizionato PIÙ IN ALTO rispetto a `{role_name}` nella lista dei ruoli del server. Errore: {e}")

@bot.tree.command(name="next_tier", description="Completely finish the current session and close this ticket")
async def next_tier(interaction: discord.Interaction):
    is_tester = any(role.name == "Tester" for role in interaction.user.roles)
    is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if not (is_tester or is_owner_role or is_admin):
        await interaction.response.send_message("❌ Devi avere il ruolo Tester o Owner per usare questo comando.", ephemeral=True)
        return

    channel = interaction.channel
    if "🟢-test-" in channel.name or "⏳-wait-" in channel.name:
        await interaction.response.send_message("Chiusura della sessione e rimozione del canale in corso (5 secondi)...")
        await asyncio.sleep(5)
        await channel.delete()
    else:
        await interaction.response.send_message("❌ Questo comando può essere usato solo all'interno di un canale ticket di test!", ephemeral=True)

# Avvio del server Flask per mantenere in vita il processo
keep_alive()

# Caricamento del Token dalle variabili d'ambiente di Render ed esecuzione del bot
TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
