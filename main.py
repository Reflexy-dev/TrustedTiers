import discord
from discord.ext import commands
from discord import app_commands
import os
from flask import Flask
from threading import Thread
import asyncio
from datetime import datetime, timedelta

# --- CONFIGURAZIONE FLASK ---
app = Flask('')
@app.route('/')
def home(): return "Bot is online!"
def run(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
def keep_alive(): Thread(target=run).start()

# --- CONFIGURAZIONE DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

GAMEMODE_EMOJIS = {
    "Sword": "⚔️", "Axe": "🪓", "UHC": "🍎", "DiaPot": "💎", "NethPot": "🔥",
    "DiaSMP": "🛡️", "SMP": "🏡", "SpearMace": "🔱", "Mace": "🔨", "Cart": "🛒", "Crystal": "🔮"
}
GAMEMODES = list(GAMEMODE_EMOJIS.keys())

# Strutture dati per gestire le nuove logiche
queues = {gm: [] for gm in GAMEMODES}  # Coda di dizionari per modalità
cooldowns = {}                         # user_id: datetime di sblocco

# Controllo se l'utente è già in una coda qualsiasi
def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

# Funzione ausiliaria per generare il grafico testuale della coda
def generate_queue_chart(gamemode, tester_mention="Nessun Tester"):
    emoji = GAMEMODE_EMOJIS.get(gamemode, "❓")
    chart = f"📊 **TABELLONE CODA {gamemode.upper()}** {emoji}\n"
    chart += f"└─ 🧑‍🏫 **Tester Attivo:** {tester_mention}\n"
    chart += "-----------------------------------------\n"
    
    if not queues[gamemode]:
        chart += "🟩 *La coda è attualmente vuota! No player in attesa.*\n"
    else:
        for idx, player in enumerate(queues[gamemode], start=1):
            chart += f"**[{idx}]** 👤 Player: <@{player['user_id']}> | 🎮 MC: `{player['mc_name']}`\n"
            
    chart += "-----------------------------------------\n"
    chart += "*Usa `/next` per far avanzare la coda di una casella.*"
    return chart

# Finestra per inserire i dati del test (Il nome viene inserito in automatico)
class FastResultModal(discord.ui.Modal, title="Inserimento Rapido Risultati"):
    def __init__(self, player_member, mc_name, gamemode):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        
        # Campi precompilati nel titolo o mostrati come etichette fisse
        self.score = discord.ui.TextInput(label=f"Punteggio per {mc_name}", placeholder="es. 3-0, 2-1", required=True)
        self.prev_rank = discord.ui.TextInput(label="Tier Precedente", placeholder="es. Unranked, LT5", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="Nuovo Tier Guadagnato", placeholder="es. LT4, HT2, LT1", required=True)
        
        self.add_item(self.score)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        rank_earned = self.new_rank.value.upper().strip()
        score_val = self.score.value
        prev_rank_val = self.prev_rank.value
        emoji = GAMEMODE_EMOJIS.get(self.gamemode, "🏆")
        
        # Calcolo URL Skin del giocatore
        skin_url = f"https://crafatar.com{self.mc_name}?overlay"
        
        # Creazione dell'Embed delle Tier List reali
        embed = discord.Embed(color=0x2f3136)
        embed.set_author(name=f"Risultati Test di {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Gamemode:", value=f"{emoji} `{self.gamemode}` (Punteggio: {score_val})", inline=False)
        embed.add_field(name="Username MC:", value=f"*{self.mc_name}* ({self.player_member.mention})", inline=False)
        embed.add_field(name="Tier Precedente:", value=prev_rank_val, inline=True)
        embed.add_field(name="Nuovo Tier Guadagnato:", value=f"**{rank_earned}**", inline=True)
        embed.set_thumbnail(url=skin_url)
        
        # Decisione del canale di destinazione in base alla fascia del Rank
        high_ranks = ["LT2", "HT2", "LT1", "HT1"]
        channel_name = "high-results" if any(hr in rank_earned for hr in high_ranks) else "results"
        
        target_channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        
        if target_channel:
            msg = await target_channel.send(embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions: await msg.add_reaction(emo)
            await interaction.followup.send(f"✅ Risultati inviati con successo in {target_channel.mention}!")
        else:
            # Se il canale non esiste, lo manda dove si trova il tester per sicurezza
            msg = await interaction.followup.send(content=f"⚠️ Canale `#{channel_name}` non trovato. Ecco l'embed:", embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions: await msg.add_reaction(emo)

        # Attivazione del Cooldown di 7 giorni per il player testato
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        # Assegnazione del ruolo automatica
        role_name = f"{rank_earned} {self.gamemode}"
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try:
                role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Enter your Minecraft Username", placeholder="e.g. Stev3_", required=True)
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # 1. BLOCCO MULTI-CODA: Controlla se è già iscritto a un altro test
        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ Sei già in coda per una modalità! Non puoi iscriverti a più test contemporaneamente.", ephemeral=True)
            return
            
        # 2. BLOCCO COOLDOWN 7 GIORNI: Controlla se ha fatto un test di recente
        if user_id in cooldowns:
            remaining = cooldowns[user_id] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                giorni = remaining.days
                await interaction.response.send_message(f"❌ Sei in cooldown! Potrai richiedere un nuovo test tra **{giorni} giorni**.", ephemeral=True)
                return
        
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # Creazione canale provvisorio di attesa (verrà eliminato automaticamente al via)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=False),
        }
        tester_role = discord.utils.get(guild.roles, name="Tester")
        if tester_role: overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"⏳-wait-{self.gamemode.lower()}-{interaction.user.name}"
        ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
        
        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value,
            'ticket_channel_id': ticket_channel.id
        }
        
        # Inserimento nella casella corretta della coda
        queues[self.gamemode].append(player_data)
        
        # Genera il tabellone aggiornato nel canale del ticket
        chart_view = generate_queue_chart(self.gamemode)
        await ticket_channel.send(chart_view)
        await interaction.followup.send(f"Iscrizione completata! Controlla il canale dedicato: {ticket_channel.mention}", ephemeral=True)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Scegli la modalità da testare...", options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values[0]))

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())

@bot.event
async def on_ready():
    print(f"Bot pronto come {bot.user.name}")
    try: await bot.tree.sync()
    except Exception as e: print(e)

@bot.command()
@commands.is_owner()
async def setup_queue(ctx):
    embed = discord.Embed(title="⚔️ Sistema Richiesta Tierlist", description="Seleziona la modalità dal menu a tendina per inserirti nel grafico della coda.", color=discord.Color.blue())
    await ctx.send(embed=embed, view=MainTicketView())

# --- NUOVO COMANDO INTERATTIVO /NEXT PER SCALARE LE CASELLE ---
@bot.tree.command(name="next", description="Avanza la coda di una casella e compila il verdetto per il primo player")
@app_commands.describe(gamemode="La modalità di cui vuoi scalare la coda")
@app_commands.choices(gamemode=[
    app_commands.Choice(name="⚔️ Sword", value="Sword"),
    app_commands.Choice(name="🪓 Axe", value="Axe"),
    app_commands.Choice(name="🍎 UHC", value="UHC"),
    app_commands.Choice(name="💎 DiaPot", value="DiaPot"),
    app_commands.Choice(name="🔥 NethPot", value="NethPot"),
    app_commands.Choice(name="🛡️ DiaSMP", value="DiaSMP"),
    app_commands.Choice(name="🏡 SMP", value="SMP"),
    app_commands.Choice(name="🔱 SpearMace", value="SpearMace"),
    app_commands.Choice(name="🔨 Mace", value="Mace"),
    app_commands.Choice(name="🛒 Cart", value="Cart"),
    app_commands.Choice(name="🔮 Crystal", value="Crystal")
])
async def next_player(interaction: discord.Interaction, gamemode: app_commands.Choice[str]):
    # Estraiamo il valore stringa reale dalla scelta effettuata dall'utente
    gamemode_str = gamemode.value

    # Controllo permessi di chi esegue il comando
    is_tester = any(role.name == "Tester" for role in interaction.user.roles)
    is_owner = any(role.name == "Owner" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if not (is_tester or is_owner or is_admin):
        await interaction.response.send_message("❌ Solo Tester o Owner possono far scorrere il tabellone dei test.", ephemeral=True)
        return

    if gamemode_str not in queues or not queues[gamemode_str]:
        await interaction.response.send_message(f"❌ La coda per la modalità `{gamemode_str}` è attualmente vuota!", ephemeral=True)
        return

    # Estrae il primo giocatore della lista (Casella #1) e lo rimuove dalla coda
    current_player_data = queues[gamemode_str].pop(0)
    
    guild = interaction.guild
    player_member = guild.get_member(current_player_data['user_id'])
    ticket_chan_id = current_player_data['ticket_channel_id']
    
    # Elimina subito il canale di attesa del player per non accumulare stanze inutili
    wait_channel = guild.get_channel(ticket_chan_id)
    if wait_channel:
        try:
            await wait_channel.delete()
        except Exception:
            pass

    if not player_member:
        await interaction.response.send_message("⚠️ Il primo giocatore in coda sembra aver abbandonato il server. Coda aggiornata!", ephemeral=True)
        return

    # RISOLTO: Apre istantaneamente la scheda di compilazione con i dati precompilati in memoria!
    await interaction.response.send_modal(FastResultModal(
        player_member=player_member,
        mc_name=current_player_data['mc_name'],
        gamemode=gamemode_str
    ))

    # Invia un riepilogo visivo nel canale corrente per mostrare la coda aggiornata (le caselle si sono spostate)
    new_chart = generate_queue_chart(gamemode_str, tester_mention=interaction.user.mention)
    await interaction.channel.send(content=f"🔄 La coda `{gamemode_str}` è avanzata! Ecco la nuova situazione:\n{new_chart}")

# Avvio del server Flask per mantenere in vita il processo
keep_alive()

# Caricamento del Token dalle variabili d'ambiente di Render ed esecuzione del bot
bot.run(os.environ.get("DISCORD_TOKEN"))
