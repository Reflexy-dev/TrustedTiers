import discord
from discord.ext import commands
from discord import app_commands
import os
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

# Strutture dati in memoria
queues = {gm: [] for gm in GAMEMODES}
cooldowns = {}
active_testers = {gm: None for gm in GAMEMODES}

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

def generate_queue_embed(gamemode):
    emoji = GAMEMODE_EMOJIS.get(gamemode, "❓")
    embed = discord.Embed(
        title=f"{emoji} {gamemode.upper()} LIVE TESTING BOARD",
        color=discord.Color.blurple()
    )
    
    queue_list = ""
    if not queues[gamemode]:
        queue_list = "🟩 *Empty*"
    else:
        for idx, player in enumerate(queues[gamemode], start=1):
            queue_list += f"**[{idx}]** <@{player['user_id']}> — MC: `{player['mc_name']}`\n"
            
    tester_mention = f"<@{active_testers[gamemode]}>" if active_testers[gamemode] else "None"
    
    embed.add_field(name="📋 Players Waiting", value=queue_list, inline=False)
    embed.add_field(name="🧑‍🏫 Active Tester", value=tester_mention, inline=False)
    return embed


# --- MODAL PER IL RISULTATO (SUL TICKET PRIVATO) ---
class FastResultModal(discord.ui.Modal, title="Fast Test Evaluation"):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        
        self.score = discord.ui.TextInput(label=f"Match Score for {mc_name}", placeholder="e.g. 3-0, 2-1", required=True)
        self.prev_rank = discord.ui.TextInput(label="Previous Tier", placeholder="e.g. Unranked, LT5", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="New Tier Earned", placeholder="e.g. LT4, HT2, LT1", required=True)
        
        self.add_item(self.score)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.upper().strip()
        score_val = self.score.value
        prev_rank_val = self.prev_rank.value
        emoji = GAMEMODE_EMOJIS.get(self.gamemode, "🏆")
        
        skin_url = f"https://crafatar.com/avatars/{self.mc_name}?overlay"
        
        embed = discord.Embed(color=0x2f3136)
        embed.set_author(name=f"{interaction.user.display_name}'s Test Results", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Gamemode:", value=f"{emoji} `{self.gamemode}` (Score: {score_val})", inline=False)
        embed.add_field(name="MC Username:", value=f"*{self.mc_name}* ({self.player_member.mention})", inline=False)
        embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=True)
        embed.add_field(name="Rank Earned:", value=f"**{rank_earned}**", inline=True)
        embed.set_thumbnail(url=skin_url)
        
        # Controllo Canale di Destinazione (Se sopra a LT2 va su high-results)
        high_ranks = ["LT1", "HT1", "LT2", "HT2"]
        channel_name = "🥇│hight-results" if any(hr == rank_earned for hr in high_ranks) else "🏆│results"
        
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if target_channel:
            msg = await target_channel.send(embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions:
                try: await msg.add_reaction(emo)
                except Exception: pass
        
        # Imposta Cooldown di 7 giorni al player
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        # Gestione Ruoli automatica
        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        # CANCELLA IL TICKET PER SEMPRE
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass


class QuickEvalView(discord.ui.View):
    def __init__(self, p_mem, mc_n, gm, r_id):
        super().__init__(timeout=None)
        self.p_mem = p_mem
        self.mc_n = mc_n
        self.gm = gm
        self.r_id = r_id
    
    @discord.ui.button(label="Input Results & Close Ticket", style=discord.ButtonStyle.green, custom_id="input_results_fixed_btn")
    async def open_modal_inside(self, btn_interaction: discord.Interaction):
        await btn_interaction.response.send_modal(FastResultModal(self.p_mem, self.mc_n, self.gm, self.r_id))


# --- BOARD DI CONTROLLO (PERSISTENTE) ---
class StaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        
        self.join_tester_btn.custom_id = f"p_join_btn_{gamemode.lower()}"
        self.next_player_btn.custom_id = f"p_next_btn_{gamemode.lower()}"
        self.leave_session_btn.custom_id = f"p_leave_btn_{gamemode.lower()}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Solo chi ha il ruolo Tester o Admin/Owner può interagire con la board dei Tester
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        specific_role_needed = f"Tester {self.gamemode}"
        has_role = any(role.name == specific_role_needed for role in interaction.user.roles)
        is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
        
        if not (has_role or is_owner_role or is_owner_guild or is_admin):
            await interaction.response.send_message(f"❌ Devi avere il ruolo `{specific_role_needed}` o `Owner` per usare questa plancia.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple)
    async def join_tester_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if active_testers[self.gamemode] is not None:
            await interaction.response.send_message("❌ C'è già un tester attivo su questa plancia!", ephemeral=True)
            return

        active_testers[self.gamemode] = interaction.user.id
        new_embed = generate_queue_embed(self.gamemode)
        await interaction.response.edit_message(embed=new_embed, view=self)

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator

        if active_testers[self.gamemode] != interaction.user.id and not (is_owner_guild or is_admin):
            await interaction.response.send_message("❌ Devi prima cliccare su 'Join as Tester'!", ephemeral=True)
            return

        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ La coda è attualmente vuota!", ephemeral=True)
            return

        # Prende il primo giocatore della lista e lo toglie dalla coda
        current_player_data = queues[self.gamemode].pop(0)
        guild = interaction.guild
        player_member = guild.get_member(current_player_data['user_id'])

        if not player_member:
            await interaction.response.send_message("⚠️ Il player ha lasciato il server. Saltato.", ephemeral=True)
            # Aggiorna la grafica anche se il player non c'è più
            refreshed_embed = generate_queue_embed(self.gamemode)
            await interaction.response.edit_message(embed=refreshed_embed, view=self)
            return

        await interaction.response.defer()

        # CREAZIONE TICKET PRIVATO (SOLO TESTER E PLAYER CORRENTE)
        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category:
            category = await guild.create_category("🎯Tierlist")

        private_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        room_name = f"🔒-match-{self.gamemode.lower()}-{player_member.name}"
        match_room = await guild.create_text_channel(name=room_name, category=category, overwrites=private_overwrites)

        eval_view = QuickEvalView(player_member, current_player_data['mc_name'], self.gamemode, match_room.id)
        
        await match_room.send(
            content=f"⚡ **Stanza Match Privata Inizializzata**\nTester: {interaction.user.mention}\nPlayer: {player_member.mention}\n\nFate il vostro match qui. Quando avete finito, il tester deve premere il bottone sottostante per inserire i Tier e chiudere definitivamente questo canale.",
            view=eval_view
        )
        
        # Aggiorna la board principale (la coda avanza)
        refreshed_embed = generate_queue_embed(self.gamemode)
        await interaction.message.edit(embed=refreshed_embed, view=self)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator

        if active_testers[self.gamemode] != interaction.user.id and not (is_owner_guild or is_admin):
            await interaction.response.send_message("❌ Non sei tu il tester attivo.", ephemeral=True)
            return

        active_testers[self.gamemode] = None
        refreshed_embed = generate_queue_embed(self.gamemode)
        await interaction.response.edit_message(embed=new_embed, view=self)


# --- MODAL RICHIESTA NOME MINECRAFT ---
class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Inserisci il tuo Username Minecraft", placeholder="e.g. Stev3_", required=True)
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild = interaction.guild
        
        is_owner = interaction.user.id == guild.owner_id or any(role.name == "Owner" for role in interaction.user.roles)
        is_admin = interaction.user.guild_permissions.administrator
        
        if is_user_in_any_queue(user_id) and not (is_owner or is_admin):
            await interaction.response.send_message("❌ Sei già in coda per una modalità!", ephemeral=True)
            return
            
        if user_id in cooldowns and not (is_owner or is_admin):
            remaining = cooldowns[user_id] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                days, hours = divmod(hours, 24)
                await interaction.response.send_message(f"❌ Sei in cooldown! Mancano: {days}g {hours}o.", ephemeral=True)
                return
                
        await interaction.response.defer(ephemeral=True)
        
        # Aggiunge il player ai dati globali della coda
        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value
        }
        queues[self.gamemode].append(player_data)
        
        # Cerca il messaggio originale della board in quel canale per aggiornarlo in tempo reale
        # Nota: per aggiornare l'embed globale, lo staff deve aver generato la board con /setup_board
        await interaction.followup.send(f"✅ Ti sei aggiunto con successo alla coda **{self.gamemode}**! Controlla il tabellone.", ephemeral=True)


class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Scegli la gamemode da testare...", options=options, custom_id="main_gamemode_select")
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values[0]))

class MainTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GamemodeSelect())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    try:
        # Sincronizza le viste persistenti così i bottoni funzionano anche se il bot si riavvia
        for gm in GAMEMODES:
            bot.add_view(StaffControlView(gm))
        bot.add_view(MainTicketView())
        await bot.tree.sync()
        print("Sincronizzazione completata con successo!")
    except Exception as e:
        print(f"Errore di sincronizzazione: {e}")

# Canale di registrazione del menu d'apertura
@bot.tree.command(name="setup_queue", description="Genera il pannello di richiesta del test")
@app_commands.default_permissions(administrator=True)
async def setup_queue(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔️ Richiedi un Test Tierlist",
        description="Seleziona la modalità dal menu a tendina qui sotto per iscriverti alla coda ufficiale del server.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=MainTicketView())

# Comando fondamentale per creare il tabellone di controllo per i Tester
@bot.tree.command(name="setup_board", description="Genera il tabellone live di una specifica coda")
@app_commands.default_permissions(administrator=True)
async def setup_board(interaction: discord.Interaction, gamemode: str):
    # Rendi la stringa maiuscola/minuscola corretta basandoti sul dizionario
    matched_gm = next((gm for gm in GAMEMODES if gm.lower() == gamemode.lower()), None)
    if not matched_gm:
        await interaction.response.send_message("❌ Modalità non valida.", ephemeral=True)
        return
        
    embed = generate_queue_embed(matched_gm)
    await interaction.response.send_message(embed=embed, view=StaffControlView(matched_gm))

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
