import discord
from discord.ext import commands
from discord import app_commands
import os
from flask import Flask
from threading import Thread
import asyncio
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
queues = {gm: [] for gm in GAMEMODES}
cooldowns = {}

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

def generate_queue_embed(gamemode, tester_1="None"):
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
            
    embed.add_field(name="📋 Players Waiting", value=queue_list, inline=False)
    embed.add_field(name="🧑‍🏫 Active Tester", value=tester_1, inline=False)
    return embed

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
        
        skin_url = f"https://crafatar.com{self.mc_name}?overlay"
        
        embed = discord.Embed(color=0x2f3136)
        embed.set_author(name=f"{interaction.user.display_name}'s Test Results", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Gamemode:", value=f"{emoji} `{self.gamemode}` (Score: {score_val})", inline=False)
        embed.add_field(name="MC Username:", value=f"*{self.mc_name}* ({self.player_member.mention})", inline=False)
        embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=True)
        embed.add_field(name="Rank Earned:", value=f"**{rank_earned}**", inline=True)
        embed.set_thumbnail(url=skin_url)
        
        high_ranks = ["LT2", "HT2", "LT1", "HT1"]
        channel_name = "🥇│hight-results" if any(hr in rank_earned for hr in high_ranks) else "🏆│results"
        
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if target_channel:
            msg = await target_channel.send(embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions: await msg.add_reaction(emo)
        
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass

        await interaction.followup.send("✅ Evaluation submitted and channel closed!", ephemeral=True)

class QuickEvalView(discord.ui.View):
    def __init__(self, p_mem, mc_n, gm, r_id):
        super().__init__(timeout=None)
        self.p_mem = p_mem
        self.mc_n = mc_n
        self.gm = gm
        self.r_id = r_id
    
    @discord.ui.button(label="Input Results & Close", style=discord.ButtonStyle.green)
    async def open_modal_inside(self, btn_interaction: discord.Interaction):
        await btn_interaction.response.send_modal(FastResultModal(self.p_mem, self.mc_n, self.gm, self.r_id))

class StaffControlView(discord.ui.View):
    def __init__(self, gamemode):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.tester_1 = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        specific_role_needed = f"Tester {self.gamemode}"
        has_role = any(role.name == specific_role_needed for role in interaction.user.roles)
        is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
        
        if not (has_role or is_owner_role or is_owner_guild or is_admin):
            await interaction.response.send_message(f"❌ Requires `{specific_role_needed}` or `Owner` role.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple, custom_id="join_as_tester_btn")
    async def join_tester(self, interaction: discord.Interaction):
        # Impostiamo l'utente corrente come tester attivo
        self.tester_1 = interaction.user
        
        # Generiamo il nuovo embed aggiornato con la menzione corretta
        new_embed = generate_queue_embed(self.gamemode, tester_1=self.tester_1.mention)
        
        # Generiamo la nuova vista dei comandi avanzati (Next e Leave) passandole i dati correnti
        next_actions_view = ActiveStaffActionsView(self.gamemode, self.tester_1)
        
        # RISOLTO: edita il messaggio aggiornando embed e bottoni contemporaneamente, azzerando l'errore di interazione
        await interaction.response.edit_message(embed=new_embed, view=next_actions_view)

class ActiveStaffActionsView(discord.ui.View):
    def __init__(self, gamemode, current_tester):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.current_tester = current_tester

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Solo il tester che ha fatto Join (o un Admin/Owner) può premere Next o Leave
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        
        if interaction.user != self.current_tester and not (is_owner_guild or is_admin):
            await interaction.response.send_message("❌ You are not the active tester who joined this board!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_private(self, interaction: discord.Interaction):
        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ The queue is currently empty!", ephemeral=True)
            return

        current_player_data = queues[self.gamemode].pop(0)
        guild = interaction.guild
        player_member = guild.get_member(current_player_data['user_id'])

        if not player_member:
            await interaction.response.send_message("⚠️ Player left the server. Entry skipped.", ephemeral=True)
            return

        # Diciamo a Discord di attendere per evitare timeout durante la creazione delle stanze
        await interaction.response.defer()

        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category:
            category = await guild.create_category("🎯Tierlist")

        # Configurazione permessi stanza privata (Tester + Player esaminato)
        private_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            player_member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        room_name = f"🔒-match-{self.gamemode.lower()}-{player_member.name}"
        match_room = await guild.create_text_channel(name=room_name, category=category, overwrites=private_overwrites)

        wait_channel = guild.get_channel(current_player_data['ticket_channel_id'])
        if wait_channel:
            try: await wait_channel.delete()
            except Exception: pass

        eval_view = QuickEvalView(player_member, current_player_data['mc_name'], self.gamemode, match_room.id)
        
        await match_room.send(
            content=f"⚡ Private Match Room Initialized\nTester: {interaction.user.mention}\nPlayer: {player_member.mention}\n\nThis channel is strictly private between the tester and the player. Discuss your matchmaking procedures here. Once you are finished, the tester must click the button below to compile scores.",
            view=eval_view
        )
        
        # Aggiorna il tabellone togliendo il player che è appena andato in match
        refreshed_embed = generate_queue_embed(self.gamemode, tester_1=self.current_tester.mention)
        await interaction.message.edit(embed=refreshed_embed)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session(self, interaction: discord.Interaction):
        # Resetta il tabellone allo stato iniziale con "None" come tester e rimette il tasto "Join" originale
        refreshed_embed = generate_queue_embed(self.gamemode, tester_1="None")
        await interaction.response.edit_message(embed=refreshed_embed, view=StaffControlView(self.gamemode))

class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Enter your Minecraft Username", placeholder="e.g. Stev3_", required=True)
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild = interaction.guild
        
        is_owner = interaction.user.id == guild.owner_id or any(role.name == "Owner" for role in interaction.user.roles)
        is_admin = interaction.user.guild_permissions.administrator
        
        if is_user_in_any_queue(user_id) and not (is_owner or is_admin):
            await interaction.response.send_message("❌ You are already queued up for another test!", ephemeral=True)
            return
            
        if user_id in cooldowns and not (is_owner or is_admin):
            remaining = cooldowns[user_id] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                days, hours = divmod(hours, 24)
                await interaction.response.send_message(f"❌ Cooldown active! Remaining: {days}d {hours}h.", ephemeral=True)
                return
                
        await interaction.response.defer(ephemeral=True)
        
        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category:
            category = await guild.create_category("🎯Tierlist")

        specific_tester_role = discord.utils.get(guild.roles, name=f"Tester {self.gamemode}")
        owner_role = discord.utils.get(guild.roles, name="Owner")
        
        wait_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if specific_tester_role: 
            wait_overwrites[specific_tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if owner_role: 
            wait_overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        room_name = f"⏳-wait-{self.gamemode.lower()}-{interaction.user.name}"
        private_wait_room = await guild.create_text_channel(name=room_name, category=category, overwrites=wait_overwrites)

        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value,
            'ticket_channel_id': private_wait_room.id
        }
        queues[self.gamemode].append(player_data)
        
        fancy_embed = generate_queue_embed(self.gamemode)
        staff_view = StaffControlView(self.gamemode)
        
        await private_wait_room.send(embed=fancy_embed, view=staff_view)
        await interaction.followup.send(f"✅ Success! Your waiting room has been created: {private_wait_room.mention}", ephemeral=True)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to test...", options=options)
        
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
        await bot.tree.sync()
        print("Slash commands synced successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

@bot.tree.command(name="setup_queue", description="Generate the main queue request embed panel")
@app_commands.default_permissions(administrator=True)
async def setup_queue(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select the gamemode you want to be tested in from the dropdown menu below to join the global board.\n\n⚠️ Remember: Never share your Minecraft account credentials or password here.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=MainTicketView())

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
