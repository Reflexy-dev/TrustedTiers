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
cooldowns = {}                         # user_id: datetime of expiry

def is_user_in_any_queue(user_id):
    for gm in GAMEMODES:
        if any(p['user_id'] == user_id for p in queues[gm]):
            return True
    return False

# --- SIMPLIFIED EMBED QUEUE DASHBOARD ---
def generate_queue_embed(gamemode, tester_mention="None"):
    emoji = GAMEMODE_EMOJIS.get(gamemode, "❓")
    
    embed = discord.Embed(
        title=f"{emoji} {gamemode.upper()} QUEUE",
        color=discord.Color.brand_green()
    )
    
    queue_list = ""
    if not queues[gamemode]:
        queue_list = "🟩 *Queue empty*"
    else:
        for idx, player in enumerate(queues[gamemode], start=1):
            queue_list += f"**[{idx}]** <@{player['user_id']}> — MC: `{player['mc_name']}`\n"
            
    embed.add_field(name="📋 Players", value=queue_list, inline=False)
    embed.add_field(name="🧑‍🏫 Active Tester", value=tester_mention, inline=False)
    return embed

# --- FAST EVALUATION MODAL ---
class FastResultModal(discord.ui.Modal, title="Test Evaluation"):
    def __init__(self, player_member, mc_name, gamemode, ticket_channel_id):
        super().__init__()
        self.player_member = player_member
        self.mc_name = mc_name
        self.gamemode = gamemode
        self.ticket_channel_id = ticket_channel_id
        
        self.score = discord.ui.TextInput(label=f"Score for {mc_name}", placeholder="e.g. 3-0, 2-1", required=True)
        self.prev_rank = discord.ui.TextInput(label="Previous Tier", placeholder="e.g. Unranked, LT5", default="Unranked", required=True)
        self.new_rank = discord.ui.TextInput(label="New Tier Earned", placeholder="e.g. LT4, HT2, LT1", required=True)
        
        self.add_item(self.score)
        self.add_item(self.prev_rank)
        self.add_item(self.new_rank)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
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
        channel_name = "high-results" if any(hr in rank_earned for hr in high_ranks) else "results"
        
        target_channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        
        if target_channel:
            msg = await target_channel.send(embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions: await msg.add_reaction(emo)
            await interaction.followup.send(f"✅ Results published to {target_channel.mention}!", ephemeral=True)
        else:
            msg = await interaction.followup.send(content=f"⚠️ Channel `#{channel_name}` not found.", embed=embed)
            reactions = ["👑", "🥳", "😱", "😭", "😂", "💀"]
            for emo in reactions: await msg.add_reaction(emo)

        # Apply 7 Days Cooldown (Only if player is not an Owner/Admin)
        is_player_owner = any(role.name == "Owner" for role in self.player_member.roles)
        if not (is_player_owner or self.player_member.guild_permissions.administrator or self.player_member.id == interaction.guild.owner_id):
            cooldowns[self.player_member.id] = datetime.utcnow() + timedelta(days=7)

        # Automatic Role Assignment Logic
        role_name = f"{rank_earned} {self.gamemode}"
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            try: role = await guild.create_role(name=role_name, mentionable=True, color=discord.Color.light_gray())
            except Exception: pass
        if role:
            try: await self.player_member.add_roles(role)
            except Exception: pass

        # SAFE LEAVE SEQUENCING: Remove the player from the channel
        guild = interaction.guild
        wait_channel = guild.get_channel(self.ticket_channel_id)
        if wait_channel:
            try:
                await wait_channel.set_permissions(self.player_member, overwrite=None)
                await wait_channel.edit(name=f"🟢-test-{self.gamemode.lower()}")
            except Exception:
                pass

        # Broadcast the SINGLE dashboard update here after everything is completed
        updated_embed = generate_queue_embed(self.gamemode, tester_mention=interaction.user.mention)
        await interaction.channel.send(embed=updated_embed)

# --- MINECRAFT USERNAME MODAL (TICKET CREATOR) ---
class MinecraftNameModal(discord.ui.Modal, title="Minecraft Verification"):
    mc_name = discord.ui.TextInput(
        label="Minecraft Username", 
        placeholder="Enter your exact IGN (e.g. Stev3_)", 
        required=True
    )
    
    def __init__(self, gamemode):
        super().__init__()
        self.gamemode = gamemode

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild = interaction.guild
        member = guild.get_member(user_id)
        
        # Check if user has Owner role/permissions to bypass cooldown
        is_owner = False
        if member:
            is_owner = any(role.name == "Owner" for role in member.roles) or member.guild_permissions.administrator or user_id == guild.owner_id

        if is_user_in_any_queue(user_id):
            await interaction.response.send_message("❌ You are already queued up for another gamemode test!", ephemeral=True)
            return
            
        # Cooldown check with days + hours logic (Bypassed if Owner)
        if user_id in cooldowns and not is_owner:
            remaining = cooldowns[user_id] - datetime.utcnow()
            if remaining.total_seconds() > 0:
                days = remaining.days
                hours = remaining.seconds // 3600
                await interaction.response.send_message(f"❌ You are on cooldown! You can request a new test in **{days} days and {hours} hours**.", ephemeral=True)
                return
        
        await interaction.response.defer(ephemeral=True)
        
        category = discord.utils.get(guild.categories, name="🎯Tierlist")
        if not category:
            category = await guild.create_category("🎯Tierlist")
            
        specific_tester_role_name = f"Tester {self.gamemode}"
        specific_tester_role = discord.utils.get(guild.roles, name=specific_tester_role_name)
        owner_role = discord.utils.get(guild.roles, name="Owner")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=False)
        }
        if specific_tester_role: 
            overwrites[specific_tester_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if owner_role: 
            overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"⏳-wait-{self.gamemode.lower()}-{interaction.user.name}"
        ticket_channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        
        player_data = {
            'user_id': user_id,
            'mc_name': self.mc_name.value,
            'ticket_channel_id': ticket_channel.id
        }
        
        queues[self.gamemode].append(player_data)
        
        fancy_embed = generate_queue_embed(self.gamemode)
        await ticket_channel.send(embed=fancy_embed)
        # Clean response on user screen with NO extra chat logs
        await interaction.followup.send(f"Success! Request sent. Room generated here: {ticket_channel.mention}", ephemeral=True)

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
    except Exception as e: 
        print(e)

@bot.command()
@commands.is_owner()
async def setup_queue(ctx):
    embed = discord.Embed(
        title="⚔️ Request a Tierlist Test",
        description="Select the gamemode you want to be tested in from the dropdown menu below. Remember: Never share your Minecraft account credentials or password here.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MainTicketView())

# --- LIVE INTERACTIVE /NEXT COMMAND TO ADVANCE THE BOARD ---
@bot.tree.command(name="next", description="Advance the queue by one slot and evaluate the first player")
@app_commands.describe(gamemode="The gamemode queue you want to advance")
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
    gamemode_str = gamemode.value

    # Staff Permissions Validation
    specific_role_needed = f"Tester {gamemode_str}"
    has_specific_tester_role = any(role.name == specific_role_needed for role in interaction.user.roles)
    is_owner = any(role.name == "Owner" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if not (has_specific_tester_role or is_owner or is_admin):
        await interaction.response.send_message(f"❌ You do not have the required `{specific_role_needed}` or `Owner` role to run this queue!", ephemeral=True)
        return

    if gamemode_str not in queues or not queues[gamemode_str]:
        await interaction.response.send_message(f"❌ The queue for `{gamemode_str}` is currently empty!", ephemeral=True)
        return

    # Extract first player info from array safely
    current_player_data = queues[gamemode_str]
    guild = interaction.guild
    player_member = guild.get_member(current_player_data['user_id'])

    if not player_member:
        queues[gamemode_str].pop(0)
        await interaction.response.send_message("⚠️ The first player left the server. Queue entry dismissed!", ephemeral=True)
        return

    # RISOLTO: Apre la schermata di valutazione istantaneamente senza mandare messaggi doppi o disordinati in chat
    await interaction.response.send_modal(FastResultModal(
        player_member=player_member,
        mc_name=current_player_data['mc_name'],
        gamemode=gamemode_str,
        ticket_channel_id=current_player_data['ticket_channel_id']
    ))

    # Safely remove the player data from memory
    queues[gamemode_str].pop(0)

# Start Flask Web Server for Render
keep_alive()

# Launch Bot Instance
bot.run(os.environ.get("DISCORD_TOKEN"))
