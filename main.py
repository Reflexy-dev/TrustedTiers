import discord
from discord.ext import commands
from discord import app_commands
import os
from flask import Flask
from threading import Thread
import asyncio
from datetime import datetime, timedelta

# --- FLASK CONFIGURATION FOR KEEP-ALIVE ---
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

# --- DISCORD BOT CONFIGURATION ---
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

# --- ULTRA SIMPLE EMBED QUEUE GENERATOR ---
def generate_queue_embed(gamemode, tester_1="None", tester_2="None"):
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
    embed.add_field(name="🧑‍🏫 Active Tester 1", value=tester_1, inline=True)
    embed.add_field(name="🧑‍🏫 Active Tester 2", value=tester_2, inline=True)
    return embed

# --- FAST EVALUATION MODAL ---
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
        
        # Apply Cooldown
        cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        # Assign Discord Tier Role
        role_name = f"{rank_earned} {self.gamemode}"
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        # Clean up the private channel after evaluation
        wait_channel = guild.get_channel(self.ticket_channel_id)
        if wait_channel:
            try: await wait_channel.delete()
            except Exception: pass

        await interaction.followup.send("✅ Evaluation submitted and channel closed!", ephemeral=True)

# --- ADVANCED DYNAMIC STAFF DASHBOARD VIEW ---
class StaffControlView(discord.ui.View):
    def __init__(self, gamemode):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.tester_1 = None
        self.tester_2 = None

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
        if self.tester_1 is None:
            self.tester_1 = interaction.user
        elif self.tester_2 is None and self.tester_1 != interaction.user:
            self.tester_2 = interaction.user
        else:
            await interaction.response.send_message("❌ Both Tester slots are currently full or you are already joined!", ephemeral=True)
            return

        new_embed = generate_queue_embed(self.gamemode, 
                                         tester_1=self.tester_1.mention if self.tester_1 else "None", 
                                         tester_2=self.tester_2.mention if self.tester_2 else "None")
        await interaction.response.edit_message(embed=new_embed, view=ActiveStaffActionsView(self.gamemode, self))

class ActiveStaffActionsView(discord.ui.View):
    def __init__(self, gamemode, parent_view):
        super().__init__(timeout=None)
        self.gamemode = gamemode
        self.parent = parent_view

    @discord.ui.button(label="Next Player", style=discord.ButtonStyle.green)
    async def next_player_private(self, interaction: discord.Interaction):
        if not queues[self.gamemode]:
            await interaction.response.send_message("❌ The queue is currently empty!", ephemeral=True)
            return

        player_index = 0
        if interaction.user == self.parent.tester_2 and len(queues[self.gamemode]) > 1:
            player_index = 1

        current_player_data = queues[self.gamemode].pop(player_index)
        guild = interaction.guild
        player_member = guild.get_member(current_player_data['user_id'])

        if not player_member:
            await interaction.response.send_message("⚠️ Player left the server. Entry skipped.", ephemeral=True)
            return

        # Open the evaluation input immediately
        await interaction.response.send_modal(FastResultModal(
            player_member=player_member,
            mc_name=current_player_data['mc_name'],
            gamemode=self.gamemode,
            ticket_channel_id=current_player_data['ticket_channel_id']
        ))

        # Alert the private room that the test is starting
        private_room = guild.get_channel(current_player_data['ticket_channel_id'])
        if private_room:
            await private_room.send(f"⚡ **Evaluation Started!**\nTester {interaction.user.mention} is currently compiling your stats. Please stay ready.")

        # Update the live board embed layout
        t1_m = self.parent.tester_1.mention if self.parent.tester_1 else "None"
        t2_m = self.parent.tester_2.mention if self.parent.tester_2 else "None"
        refreshed_embed = generate_queue_embed(self.gamemode, tester_1=t1_m, tester_2=t2_m)
        await interaction.message.edit(embed=refreshed_embed)

    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.red)
    async def leave_session(self, interaction: discord.Interaction):
        if interaction.user == self.parent.tester_1:
            self.parent.tester_1 = None
        elif interaction.user == self.parent.tester_2:
            self.parent.tester_2 = None
        else:
            await interaction.response.send_message("❌ You are not an active tester on this board.", ephemeral=True)
            return

        t1_m = self.parent.tester_1.mention if self.parent.tester_1 else "None"
        t2_m = self.parent.tester_2.mention if self.parent.tester_2 else "None"
        refreshed_embed = generate_queue_embed(self.parent.gamemode, tester_1=t1_m, tester_2=t2_m)
        next_view = self.parent if (self.parent.tester_1 or self.parent.tester_2) else StaffControlView(self.gamemode)
        await interaction.response.edit_message(embed=refreshed_embed, view=next_view)

# --- MINECRAFT USERNAME MODAL (TICKET CREATOR) ---
class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(label="Enter your Minecraft Username", placeholder="e.g. Stev3_", required=True)
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild = interaction.guild
        
        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ You are already queued up for another test!", ephemeral=True)
            return
            
        is_owner = interaction.user.id == guild.owner_id or any(role.name == "Owner" for role in interaction.user.roles)
        
        if user_id in cooldowns and not is_owner:
            remaining = cooldowns[user_id] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                days, hours = divmod(hours, 24)
                await interaction.response.send_message(f"❌ Cooldown active! Remaining: {days}d {hours}h.", ephemeral=True)
                return
                
        await interaction.response.defer(ephemeral=True)
        
        # 1. RISOLTO: Creazione immediata del canale privato dentro 🎯Tierlist appena il player si iscrive!
        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category:
            category = await guild.create_category("🎯Tierlist")

        specific_tester_role = discord.utils.get(guild.roles, name=f"Tester {self.gamemode}")
        owner_role = discord.utils.get(guild.roles, name="Owner")
        
        # Blind channel configuration (Solo il player e lo staff specifico vedono questa stanza)
        private_overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if specific_tester_role: 
            private_overwrites[specific_tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if owner_role: 
            private_overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        room_name = f"⏳-{self.gamemode.lower()}-{interaction.user.name}"
        private_room = await guild.create_text_channel(name=room_name, category=category, overwrites=private_overwrites)

        # Salviamo l'ID esatto della stanza appena creata
        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value,
            'ticket_channel_id': private_room.id
        }
        queues[self.gamemode].append(player_data)
        
        # Welcoming instructions printed inside the new isolated waiting zone
        await private_room.send(
            f"⚡ Welcome to your private {self.gamemode} Testing Room!\n"
            f"Player: {interaction.user.mention}\n"
            f"Minecraft Account: {self.mc_name.value}\n\n"
            f"Please wait here. An authorized tester will open your evaluation shortly."
        )
        await interaction.followup.send(f"✅ Success! Your private room has been created: {private_room.mention}", ephemeral=True)

# --- DROPDOWN INTERFACE COMPONENTS ---
class GamemodeSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=gm, emoji=GAMEMODE_EMOJIS[gm]) for gm in GAMEMODES]
        super().__init__(placeholder="Choose a gamemode to test...", options=options)
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MinecraftNameModal(self.values))

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

@bot.command()
@commands.is_owner()
async def setup_queue(ctx):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select the gamemode you want to be tested in from the dropdown menu below to join the global board.\n\n⚠️ Remember: Never share your Minecraft account credentials or password here.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MainTicketView())

# Start Flask Web Server
keep_alive()

# Launch Bot Instance
bot.run(os.environ.get("DISCORD_TOKEN"))
