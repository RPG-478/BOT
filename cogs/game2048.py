```python
import discord
from discord.ext import commands
from discord import app_commands
import random
import io
from PIL import Image, ImageDraw, ImageFont

class Game2048(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="2048", description="Start a game of 2048")
    async def start_2048(self, interaction: discord.Interaction):
        """Starts a new 2048 game session."""
        view = Game2048View(interaction.user.id)
        image_file = view.generate_board_image()
        
        embed = discord.Embed(title="2048 Game", color=0xFFFFFF)
        embed.set_image(url="attachment://board.png")
        embed.set_footer(text=f"Player: {interaction.user.display_name} | Score: 0")
        
        await interaction.response.send_message(embed=embed, file=image_file, view=view)

class Game2048View(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.size = 4
        self.board = [[0] * self.size for _ in range(self.size)]
        self.score = 0
        self.game_over = False
        self.won = False
        
        # Initialize board with two random tiles
        self.add_random_tile()
        self.add_random_tile()

    def add_random_tile(self):
        empty_cells = [(r, c) for r in range(self.size) for c in range(self.size) if self.board[r][c] == 0]
        if empty_cells:
            r, c = random.choice(empty_cells)
            self.board[r][c] = 2 if random.random() < 0.9 else 4

    def generate_board_image(self):
        """Generates the 2048 board image using Pillow."""
        cell_size = 100
        padding = 10
        img_size = self.size * cell_size + (self.size + 1) * padding
        image = Image.new("RGB", (img_size, img_size), "#bbada0")
        draw = ImageDraw.Draw(image)
        
        # Colors for 2048 tiles
        bg_colors = {
            0: "#cdc1b4", 2: "#eee4da", 4: "#ede0c8", 8: "#f2b179",
            16: "#f59563", 32: "#f67c5f", 64: "#f65e3b", 128: "#edcf72",
            256: "#edcc61", 512: "#edc850", 1024: "#edc53f", 2048: "#edc22e"
        }
        text_colors = {
            2: "#776e65", 4: "#776e65", 8: "#f9f6f2", 16: "#f9f6f2",
            32: "#f9f6f2", 64: "#f9f6f2", 128: "#f9f6f2", 256: "#f9f6f2",
            512: "#f9f6f2", 1024: "#f9f6f2", 2048: "#f9f6f2"
        }

        # Try to load a font, fallback to default
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()

        for r in range(self.size):
            for c in range(self.size):
                val = self.board[r][c]
                x = padding + c * (cell_size + padding)
                y = padding + r * (cell_size + padding)
                
                # Draw cell background
                color = bg_colors.get(val, "#3c3a32")
                draw.rounded_rectangle([x, y, x + cell_size, y + cell_size], radius=5, fill=color)
                
                # Draw number
                if val != 0:
                    txt = str(val)
                    t_color = text_colors.get(val, "#f9f6f2")
                    # Calculate text position to center it
                    bbox = draw.textbbox((0, 0), txt, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    draw.text((x + (cell_size - tw) / 2, y + (cell_size - th) / 2 - 5), txt, fill=t_color, font=font)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return discord.File(buffer, filename="board.png")

    def move(self, direction):
        """Logic for moving tiles in 4 directions."""
        def compress(row):
            new_row = [i for i in row if i != 0]
            new_row += [0] * (self.size - len(new_row))
            return new_row

        def merge(row):
            for i in range(self.size - 1):
                if row[i] != 0 and row[i] == row[i+1]:
                    row[i] *= 2
                    self.score += row[i]
                    if row[i] == 2048:
                        self.won = True
                    row[i+1] = 0
            return row

        moved = False
        old_board = [row[:] for row in self.board]

        for i in range(self.size):
            if direction in ["up", "down"]:
                row = [self.board[j][i] for j in range(self.size)]
                if direction == "down": row.reverse()
                
                row = compress(row)
                row = merge(row)
                row = compress(row)
                
                if direction == "down": row.reverse()
                for j in range(self.size):
                    self.board[j][i] = row[j]
            else:
                row = self.board[i][:]
                if direction == "right": row.reverse()
                
                row = compress(row)
                row = merge(row)
                row = compress(row)
                
                if direction == "right": row.reverse()
                self.board[i] = row

        if self.board != old_board:
            moved = True
            self.add_random_tile()
        
        if not any(0 in row for row in self.board):
            if not self.can_move():
                self.game_over = True
        
        return moved

    def can_move(self):
        """Checks if any move is possible."""
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] == 0: return True
                if r < self.size - 1 and self.board[r][c] == self.board[r+1][c]: return True
                if c < self.size - 1 and self.board[r][c] == self.board[r][c+1]: return True
        return False

    async def update_message(self, interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This is not your game!", ephemeral=True)

        image_file = self.generate_board_image()
        color = 0xFFFFFF
        status_text = f"Player: {interaction.user.display_name} | Score: {self.score}"
        
        if self.won:
            status_text = "🎉 Congratulations! You reached 2048!"
            self.stop()
        elif self.game_over:
            status_text = "💀 Game Over! No more moves left."
            self.stop()

        embed = discord.Embed(title="2048 Game", description=status_text, color=color)
        embed.set_image(url="attachment://board.png")
        
        await interaction.response.edit_message(embed=embed, attachments=[image_file], view=self)

    @discord.ui.button(label="↑", style=discord.ButtonStyle.gray, row=0)
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.move("up")
        await self.update_message(interaction)

    @discord.ui.button(label="←", style=discord.ButtonStyle.gray, row=1)
    async def left(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.move("left")
        await self.update_message(interaction)

    @discord.ui.button(label="↓", style=discord.ButtonStyle.gray, row=1)
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.move("down")
        await self.update_message(interaction)

    @discord.ui.button(label="→", style=discord.ButtonStyle.gray, row=1)
    async def right(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.move("right")
        await self.update_message(interaction)

async def setup(bot):
    await bot.add_cog(Game2048(bot))

```
