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

# Global Data Structures
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


# --- EVALUATION MODAL ---
class FastResultModal(discord.ui.Modal, title="Fast Test Evaluation"):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        
        # Campi identici allo screenshot di MCTIERS (incluso Region)
        self.region = discord.ui.TextInput(label="Region", placeholder="e.g. EU, NA, AS", default="EU", required=True)
        self.prev_rank = discord.ui.TextInput(label="Previous Rank", placeholder="e.g. Unranked, Low Tier 5", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="Rank Earned", placeholder="e.g. Low Tier 5, High Tier 2", required=True)
        
        self.add_item(self.region)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        rank_earned = self.new_rank.value.strip()
        prev_rank_val = self.prev_rank.value.strip()
        region_val = self.region.value.upper().strip()
        
        # URL per la Skin 3D del player (MCTiers Style)
        skin_url = f"https://visage.surreal.ca/full/512/{self.mc_name}.png"
        
        # EMBED IDENTICO AL COPIATO DI MCTIERS
        embed = discord.Embed(
            color=0xdd2e44  # Colore rosso identico alla barra dello screenshot
        )
        # Imposta titolo con il nome e avatar rotondo del player a sinistra e la coppa
        embed.set_author(
            name=f"{self.mc_name}'s Test Results 🏆", 
            icon_url=self.player_member.display_avatar.url
        )
        # Visualizza la skin 3D sulla destra
        embed.set_thumbnail(url=skin_url)
        
        # Campi scritti con lo stesso identico formato (Grassetto l'intestazione, testo sotto, inline=False per averli ordinati a cascata)
        embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        embed.add_field(name="Region:", value=region_val, inline=False)
        embed.add_field(name="Username:", value=f"*{self.mc_name}*", inline=False)
        embed.add_field(name="Previous Rank:", value=prev_rank_val, inline=False)
        embed.add_field(name="Rank Earned:", value=rank_earned, inline=False)
        
        # Filtro canali risultati
        # Controlla se contiene parole chiave dei Tier alti
        high_tier_keywords = ["LT1", "HT1", "LT2", "HT2", "1", "2", "Tier 1", "Tier 2", "Low Tier 1", "High Tier 1", "Low Tier 2", "High Tier 2"]
        is_high = any(keyword.lower() in rank_earned.lower() for keyword in high_tier_keywords)
        channel_name = "🥇│hight-results" if is_high else "🏆│results"
        
        target_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if target_channel:
            # Mandiamo la menzione del giocatore @Giocatore sopra l'embed, proprio come nello screenshot
            msg = await target_channel.send(content=self.player_member.mention, embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions:
                try: await msg.add_reaction(emo)
                except Exception: pass
        
        # Cooldown di 7 giorni per il player
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        # Assegnazione automatica del ruolo (es. "Low Tier 5 Sword")
        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        # Elimina definitivamente il canale privato di match
        match_channel = guild.get_channel(self.ticket_channel_id)
        if match_channel:
            try: await match_channel.delete()
            except Exception: pass


# --- BOTTONE SEGRETO PER IL TESTER ---
class TesterPrivateEvalView(discord.ui.View):
    def __init__(self, player_member, mc_name, gamemode, channel_id):
        super().__init__(timeout=None)
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.channel_id = channel_id

    @discord.ui.button(label="⭐ Open Tier Evaluation", style=discord.ButtonStyle.green, custom_id="tester_eval_secret_btn")
    async def open_eval_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        has_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
        has_tester_role = any(role.name == f"Tester {self.gamemode}" for role in interaction.user.roles)
        
        if not (has_tester_role or has_owner_role or is_owner_guild or is_admin):
            await interaction.response.send_message("❌ Only authorized Tester staff or the Owner can trigger this evaluation!", ephemeral=True)
            return

        # Mostra il modulo di inserimento tier
        await interaction.response.send_modal(FastResultModal(
            player_member=self.player_member,
            mc_name=self.mc_name,
            gamemode=self.gamemode,
            ticket_channel_id=self.channel_id
        ))


# --- PERSISTENT STAFF CONTROL BOARD ---
class StaffControlView(discord.ui.View):
    def __init__(self, gamemode: str):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        
        self.join_tester_btn.custom_id = f"p_join_btn_{gamemode.lower()}"
        self.next_player_btn.custom_id = f"p_next_btn_{gamemode.lower()}"
        self.leave_session_btn.custom_id = f"p_leave_btn_{gamemode.lower()}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator
        specific_role_needed = f"Tester {self.gamemode}"
        has_role = any(role.name == specific_role_needed for role in interaction.user.roles)
        is_owner_role = any(role.name == "Owner" for role in interaction.user.roles)
        
        if not (has_role or is_owner_role or is_owner_guild or is_admin):
            await interaction.response.send_message(f"❌ You need the `{specific_role_needed}` or `Owner` role to use this board.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join as Tester", style=discord.ButtonStyle.blurple)
    async def join_tester_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if active_testers[self.gamemode] is not None:
            await interaction.response.send_message("❌ A tester is already active on this board!", ephemeral=True)
            return

        active_testers[self.gamemode] = interaction.user.id
        new_embed = generate_queue_embed(self.gamemode)
        await interaction.response.edit_message(embed=new_embed, view=self)

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator

        if active_testers[self.gamemode] != interaction.user.id and not (is_owner_guild or is_admin):
            await interaction.response.send_message("❌ You must click 'Join as Tester' first!", ephemeral=True)
            return

        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ The queue is currently empty!", ephemeral=True)
            return

        current_player_data = queues[self.gamemode].pop(0)
        guild = interaction.guild
        player_member = guild.get_member(current_player_data['user_id'])

        if not player_member:
            await interaction.response.send_message("⚠️ Player left the server. Skipped.", ephemeral=True)
            refreshed_embed = generate_queue_embed(self.gamemode)
            await interaction.response.edit_message(embed=refreshed_embed, view=self)
            return

        # Nascondi la waitlist al player
        try:
            await interaction.channel.set_permissions(player_member, overwrite=None)
        except Exception:
            pass

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

        # Invio della risposta EFFIMERA (invisibile al player) per il Tester
        eval_view = TesterPrivateEvalView(player_member, current_player_data['mc_name'], self.gamemode, match_room.id)
        await interaction.response.send_message(
            content=f"⚡ **Match Room Created:** {match_room.mention}\nThe chat inside is completely clean. Use the button below whenever you are ready to input the Tier and close the match.",
            view=eval_view,
            ephemeral=True
        )
        
        # Aggiorna la waitlist visibile sul server
        refreshed_embed = generate_queue_embed(self.gamemode)
        await interaction.message.edit(embed=refreshed_embed, view=self)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_owner_guild = interaction.user.id == interaction.guild.owner_id
        is_admin = interaction.user.guild_permissions.administrator

        if active_testers[self.gamemode] != interaction.user.id and not (is_owner_guild or is_admin):
            await interaction.response.send_message("❌ You are not the active tester.", ephemeral=True)
            return

        active_testers[self.gamemode] = None
        refreshed_embed = generate_queue_embed(self.gamemode)
        await interaction.response.edit_message(embed=refreshed_embed, view=self)


# --- MINECRAFT NAME VERIFICATION MODAL ---
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
        
        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value
        }
        queues[self.gamemode].append(player_data)
        
        waitlist_channel = discord.utils.get(guild.text_channels, name=f"waitlist-{self.gamemode.lower()}")
        
        if waitlist_channel:
            await waitlist_channel.set_permissions(interaction.user, read_messages=True, send_messages=False)
            
            async for message in waitlist_channel.history(limit=20):
                if message.author == bot.user and message.embeds and "LIVE TESTING BOARD" in message.embeds[0].title:
                    refreshed_embed = generate_queue_embed(self.gamemode)
                    await message.edit(embed=refreshed_embed)
                    break
            
            await interaction.followup.send(f"✅ Success! You have been added to the board. Check your assigned waitlist channel: {waitlist_channel.mention}", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Registered for {self.gamemode}! (Warning: `#waitlist-{self.gamemode.lower()}` channel not found on server)", ephemeral=True)

class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to test...", options=options, custom_id="main_gamemode_select")
        
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
        for gm in GAMEMODES:
            bot.add_view(StaffControlView(gm))
        bot.add_view(MainTicketView())
        await bot.tree.sync()
        print("Slash commands & Persistent Views synced successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.tree.command(name="setup_panel", description="Generate the main booking panel")
@app_commands.default_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select the gamemode you want to be tested in from the dropdown menu below to join the global waitlist.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=MainTicketView())


@bot.tree.command(name="setup_board", description="Create and setup the live board inside a waitlist channel")
@app_commands.default_permissions(administrator=True)
async def setup_board(interaction: discord.Interaction, gamemode: str):
    guild = interaction.guild
    matched_gm = next((gm for gm in GAMEMODES if gm.lower() == gamemode.lower()), None)
    if not matched_gm:
        await interaction.response.send_message("❌ Invalid gamemode.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    category = discord.utils.get(guild.categories, name="🎯Tierlist")
    if not category:
        category = await guild.create_category("🎯Tierlist")

    tester_role = discord.utils.get(guild.roles, name=f"Tester {matched_gm}")
    owner_role = discord.utils.get(guild.roles, name="Owner")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
    }
    if tester_role:
        overwrites[tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    channel_name = f"waitlist-{matched_gm.lower()}"
    waitlist_channel = discord.utils.get(guild.text_channels, name=channel_name)
    
    if not waitlist_channel:
        waitlist_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)

    embed = generate_queue_embed(matched_gm)
    await waitlist_channel.send(embed=embed, view=StaffControlView(matched_gm))
    
    await interaction.followup.send(f"✅ Board initialized and channel permissions set up in {waitlist_channel.mention}", ephemeral=True)

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
