import pygame
import random
import math

pygame.init()

# Constants
WIDTH, HEIGHT = 1000, 700
NUM_SQUADS = 3            # Number of player squads
BOIDS_PER_SQUAD = 6       # Number of drones per player squad (including leader)
BOID_RADIUS = 6
MAX_SPEED = 2
NEIGHBOR_RADIUS = 50
AVOID_RADIUS = 20
FORMATION_MODE = 'V'      # Can be 'V' or 'CIRCLE'
FONT = pygame.font.SysFont("Arial", 14)

# Colors
WHITE = (255, 255, 255)
GRAY = (180, 180, 180)
RED = (255, 60, 60)
GREEN = (60, 255, 60)
BLUE = (60, 60, 255)
YELLOW = (255, 255, 100)
PURPLE = (150, 0, 200)   # New color for enemies
ORANGE = (255, 165, 0)   # For 'ENGAGE' state indicator
COLORS = [RED, GREEN, BLUE] # Colors for player squads

# Game setup
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Advanced Drone Squad Simulation")

# --- Utility Functions ---
def distance(a, b):
    """Calculates the Euclidean distance between two points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])

def get_formation_offset(index, mode, total):
    """Calculates the offset for a boid in a given formation."""
    spacing = 30
    if mode == 'V':
        # V-formation: layer by layer, alternating sides
        layer = (index + 1) // 2
        side = -1 if index % 2 == 0 else 1
        return [side * spacing * layer, spacing * layer]
    elif mode == 'CIRCLE':
        # Circular formation
        angle = (2 * math.pi / total) * index
        radius = 60
        return [math.cos(angle) * radius, math.sin(angle) * radius]
    return [0, 0] # Default if mode is not recognized

# --- Ping Class (for communication visualization) ---
class Ping:
    def __init__(self, pos):
        self.pos = pos[:]
        self.radius = 0
        self.max_radius = 100
        self.active = True

    def update(self):
        if self.radius < self.max_radius:
            self.radius += 3 # Expand ping
        else:
            self.active = False # Deactivate when max radius is reached

    def draw(self, screen):
        if self.active:
            pygame.draw.circle(screen, GRAY, (int(self.pos[0]), int(self.pos[1])), int(self.radius), 1)

# --- Projectile Class (for combat) ---
class Projectile:
    def __init__(self, pos, target_boid):
        self.pos = list(pos)
        self.target_boid = target_boid # Reference to the target Boid object
        self.velocity = [0, 0] # Initial velocity, calculated in update
        self.speed = 5
        self.active = True

    def update(self):
        if not self.active or self.target_boid.health <= 0:
            self.active = False # Deactivate if already inactive or target is destroyed
            return

        # Aim towards the current position of the target
        dx, dy = self.target_boid.position[0] - self.pos[0], self.target_boid.position[1] - self.pos[1]
        dist = distance(self.pos, self.target_boid.position)
        if dist > 0:
            self.velocity = [dx / dist * self.speed, dy / dist * self.speed]
        else:
            self.velocity = [0, 0] # Stop if on top of target

        self.pos[0] += self.velocity[0]
        self.pos[1] += self.velocity[1]

        # Check for collision with the target
        if distance(self.pos, self.target_boid.position) < BOID_RADIUS:
            if not self.target_boid.shielded:
                self.target_boid.health -= 5 # Apply damage if not shielded
            self.active = False # Deactivate after hitting

    def draw(self, screen):
        if self.active:
            pygame.draw.circle(screen, YELLOW, (int(self.pos[0]), int(self.pos[1])), 3)

# --- Boid Class (main drone entity) ---
class Boid:
    def __init__(self, x, y, squad_id, is_leader=False, index=0, is_enemy=False):
        self.position = [x, y]
        self.velocity = [random.uniform(-1, 1), random.uniform(-1, 1)]
        self.squad_id = squad_id
        self.is_leader = is_leader
        self.index_in_squad = index
        self.leader_ref = None          # Reference to its leader Boid object
        self.formation_offset = [0, 0]
        self.label = f"L{index+1}" if is_leader else f"F{index+1}" # Label for display
        self.waypoints = []             # List of patrol points for leaders
        self.current_wp = 0
        self.health = 100
        self.attacking = False          # Flag to indicate active attack
        self.target_enemy = None        # Reference to the enemy Boid object being targeted
        self.is_medic = (index == 0 and not is_leader and not is_enemy) # Medic role
        self.shielded = False           # Shield status
        self.shield_timer = 0           # Timer for shield duration
        self.projectile_cooldown = 0    # Cooldown for firing projectiles
        self.is_enemy = is_enemy        # Flag to distinguish enemies from player drones
        self.firing_range = 200         # Range within which boid can fire
        self.detection_range = 300      # Range within which boid can detect enemies
        self.state = 'PATROL'           # Initial state for AI ('PATROL', 'ENGAGE', 'EVADE')

    def add_waypoint(self, pos):
        """Adds a waypoint to the boid's patrol path."""
        self.waypoints.append(pos)

    def heal_ally(self, all_boids):
        """Medics heal nearby allies in their own squad."""
        if self.is_medic:
            # Filter allies to only include drones from the same squad (and not itself)
            squad_allies = [b for b in all_boids if b.squad_id == self.squad_id and b != self and not b.is_enemy]
            for ally in squad_allies:
                if distance(self.position, ally.position) < 60 and ally.health < 100:
                    ally.health += 0.2 # Small healing amount
                    if ally.health > 100:
                        ally.health = 100

    def apply_shield(self, all_boids):
        """Leader applies shield to its squad members."""
        if self.is_leader and not self.is_enemy and self.shield_timer <= 0: # Only player leaders can shield
            # Find all non-leader player boids in the same squad
            squad_members_to_shield = [b for b in all_boids if b.squad_id == self.squad_id and not b.is_leader and not b.is_enemy]
            for ally in squad_members_to_shield:
                ally.shielded = True
                ally.shield_timer = 180 # Shield lasts for 3 seconds (60 FPS * 3)
            self.shield_timer = 600 # Leader's cooldown for next shield activation (10 seconds)

    def update(self, all_boids, squad_size):
        """Updates the boid's state and position."""
        if self.health <= 0:
            return # Dead boids don't update

        # Decrement timers
        if self.projectile_cooldown > 0:
            self.projectile_cooldown -= 1
        if self.shield_timer > 0:
            self.shield_timer -= 1
        if self.shielded and self.shield_timer <= 0:
            self.shielded = False # Shield expires

        # --- State Machine Logic ---
        if self.state == 'PATROL':
            self.handle_patrol(all_boids, squad_size)
        elif self.state == 'ENGAGE':
            self.handle_engage(all_boids)
        elif self.state == 'EVADE':
            self.handle_evade(all_boids)
        # Add more states as needed (e.g., 'REGROUP', 'HEAL_MODE')

        # --- Flocking Behaviors (applied generally) ---
        # Cohesion, Alignment, Separation
        neighbors = [b for b in all_boids if b != self and distance(self.position, b.position) < NEIGHBOR_RADIUS]
        if neighbors:
            # Cohesion: move towards average position of neighbors
            avg_pos = [sum(b.position[0] for b in neighbors) / len(neighbors),
                       sum(b.position[1] for b in neighbors) / len(neighbors)]
            self.velocity[0] += 0.01 * (avg_pos[0] - self.position[0])
            self.velocity[1] += 0.01 * (avg_pos[1] - self.position[1])

            # Alignment: steer towards average heading of neighbors
            avg_vel = [sum(b.velocity[0] for b in neighbors) / len(neighbors),
                       sum(b.velocity[1] for b in neighbors) / len(neighbors)]
            self.velocity[0] += 0.05 * (avg_vel[0] - self.velocity[0])
            self.velocity[1] += 0.05 * (avg_vel[1] - self.velocity[1])

            # Separation: avoid crowding neighbors
            for b in neighbors:
                if distance(self.position, b.position) < AVOID_RADIUS:
                    self.velocity[0] += (self.position[0] - b.position[0]) * 0.05
                    self.velocity[1] += (self.position[1] - b.position[1]) * 0.05

        # Cap speed
        speed = math.hypot(*self.velocity)
        if speed > MAX_SPEED:
            self.velocity[0] = self.velocity[0] / speed * MAX_SPEED
            self.velocity[1] = self.velocity[1] / speed * MAX_SPEED

        # Update position
        self.position[0] += self.velocity[0]
        self.position[1] += self.velocity[1]

        # Wrap around screen edges
        self.position[0] %= WIDTH
        self.position[1] %= HEIGHT

        # Heal allies if medic (checked after position update for accurate distance)
        self.heal_ally(all_boids)

    def handle_patrol(self, all_boids, squad_size):
        """Behavior when in PATROL state."""
        # Leader patrol logic
        if self.is_leader:
            if self.waypoints:
                target = self.waypoints[self.current_wp]
                dx, dy = target[0] - self.position[0], target[1] - self.position[1]
                if distance(self.position, target) < 10: # Reached waypoint
                    self.current_wp = (self.current_wp + 1) % len(self.waypoints)
                else:
                    self.velocity[0] += 0.05 * dx
                    self.velocity[1] += 0.05 * dy

        # Follower patrol logic (move towards leader's formation spot)
        else:
            if self.leader_ref and self.leader_ref.health > 0: # Ensure leader is alive
                self.formation_offset = get_formation_offset(self.index_in_squad, FORMATION_MODE, squad_size)
                target = [self.leader_ref.position[0] + self.formation_offset[0],
                          self.leader_ref.position[1] + self.formation_offset[1]]
                dx, dy = target[0] - self.position[0], target[1] - self.position[1]
                self.velocity[0] += 0.04 * dx
                self.velocity[1] += 0.04 * dy
            else: # If leader is dead, the follower might become rogue or seek a new leader
                self.leader_ref = None # No leader, so just wander or try to find a new one

        # Transition to ENGAGE if an enemy is detected
        potential_enemies = [b for b in all_boids if b.is_enemy != self.is_enemy and b.health > 0]
        enemies_in_detection_range = [b for b in potential_enemies if distance(self.position, b.position) < self.detection_range]

        if enemies_in_detection_range:
            self.target_enemy = min(enemies_in_detection_range, key=lambda e: distance(self.position, e.position))
            self.state = 'ENGAGE'
            self.attacking = True # Set attacking flag

    def handle_engage(self, all_boids):
        """Behavior when in ENGAGE state."""
        if self.target_enemy and self.target_enemy.health > 0:
            # Move towards target if out of firing range, or maintain distance
            if distance(self.position, self.target_enemy.position) > self.firing_range * 0.8:
                dx, dy = self.target_enemy.position[0] - self.position[0], self.target_enemy.position[1] - self.position[1]
                self.velocity[0] += 0.05 * dx
                self.velocity[1] += 0.05 * dy
            else: # When in firing range, slow down to aim and fire
                self.velocity[0] *= 0.9
                self.velocity[1] *= 0.9

            # Fire projectiles if cooldown is ready and target is in range
            if self.projectile_cooldown == 0 and distance(self.position, self.target_enemy.position) <= self.firing_range:
                projectiles.append(Projectile(self.position, self.target_enemy))
                self.projectile_cooldown = 60 # 1 second cooldown (60 frames)
        else:
            # Target is destroyed or lost, transition back to PATROL
            self.attacking = False
            self.target_enemy = None
            self.state = 'PATROL'

        # Consider evading if health is low while engaging (optional)
        if self.health < 30 and not self.is_enemy: # Only player boids might evade
            self.state = 'EVADE'

    def handle_evade(self, all_boids):
        """Behavior when in EVADE state."""
        threats = [b for b in all_boids if b.is_enemy != self.is_enemy and b.health > 0 and distance(self.position, b.position) < self.detection_range * 1.5]
        if threats:
            # Move away from the closest threat
            closest_threat = min(threats, key=lambda t: distance(self.position, t.position))
            dx, dy = self.position[0] - closest_threat.position[0], self.position[1] - closest_threat.position[1]
            # Boost velocity away from threat
            self.velocity[0] += dx * 0.1
            self.velocity[1] += dy * 0.1
            # Ensure a minimum speed when evading
            speed = math.hypot(*self.velocity)
            if speed < MAX_SPEED / 2: # Keep moving
                self.velocity[0] = self.velocity[0] / speed * (MAX_SPEED / 2) if speed > 0 else (random.uniform(-1, 1) * MAX_SPEED / 2)
                self.velocity[1] = self.velocity[1] / speed * (MAX_SPEED / 2) if speed > 0 else (random.uniform(-1, 1) * MAX_SPEED / 2)
        else:
            # No immediate threats, return to patrol or regroup
            if self.health > 50: # Only return to patrol if health is sufficiently recovered
                self.state = 'PATROL'
            else:
                # Still low health, maybe try to find a medic (future feature)
                self.state = 'PATROL' # For now, just go back to patrol

    def draw(self, screen):
        """Draws the boid on the screen."""
        if self.health <= 0:
            return

        # Determine color based on role/type
        color = PURPLE if self.is_enemy else (YELLOW if self.is_medic else COLORS[self.squad_id % len(COLORS)])
        pygame.draw.circle(screen, color, (int(self.position[0]), int(self.position[1])), BOID_RADIUS)

        # Draw label
        label = FONT.render(self.label, True, WHITE)
        screen.blit(label, (int(self.position[0]) + 10, int(self.position[1]) - 10))

        # Draw health bar
        health_bar_length = 30
        health_ratio = self.health / 100
        pygame.draw.rect(screen, RED, (self.position[0] - 15, self.position[1] - 15, health_bar_length, 4))
        pygame.draw.rect(screen, GREEN, (self.position[0] - 15, self.position[1] - 15, health_bar_length * health_ratio, 4))

        # Draw special indicators
        if self.is_leader:
            pygame.draw.circle(screen, WHITE, (int(self.position[0]), int(self.position[1])), BOID_RADIUS + 2, 1)
        if self.shielded:
            pygame.draw.circle(screen, BLUE, (int(self.position[0]), int(self.position[1])), BOID_RADIUS + 4, 1)
        if self.state == 'ENGAGE':
             pygame.draw.circle(screen, ORANGE, (int(self.position[0]), int(self.position[1])), BOID_RADIUS + 6, 1) # Orange border for attacking
        if self.is_medic: # Additional visual for medic
            pygame.draw.line(screen, WHITE, (self.position[0] - 5, self.position[1]), (self.position[0] + 5, self.position[1]), 1)
            pygame.draw.line(screen, WHITE, (self.position[0], self.position[1] - 5), (self.position[0], self.position[1] + 5), 1)

# --- Game Initialization ---
patrol_zones = []
zone_width = WIDTH // NUM_SQUADS
for i in range(NUM_SQUADS):
    patrol_zones.append(pygame.Rect(i * zone_width, 0, zone_width, HEIGHT))

boids = []          # List to hold all boids (player and enemy)
pings = []          # List to hold active pings
projectiles = []    # List to hold active projectiles

# --- Create Player Squads ---
for squad_id in range(NUM_SQUADS):
    leader = Boid(150 + squad_id * 300, HEIGHT // 2, squad_id, is_leader=True)
    leader.label = f"L{squad_id + 1}"
    # Assign waypoints for the leader to patrol
    leader.add_waypoint((100 + squad_id * 300, 150))
    leader.add_waypoint((100 + squad_id * 300, 550))
    boids.append(leader)
    for i in range(BOIDS_PER_SQUAD - 1): # -1 because leader is already added
        # Create follower boids, linking them to their leader
        b = Boid(150 + squad_id * 300 + random.randint(-20, 20), HEIGHT // 2 + random.randint(-20, 20), squad_id, index=i)
        b.leader_ref = leader
        boids.append(b)

# --- Create Enemy Boids (Programmatic Generation) ---
NUM_ENEMY_SQUADS = 2 # Number of enemy squads
BOIDS_PER_ENEMY_SQUAD = 4 # Number of boids per enemy squad
ENEMY_START_SQUAD_ID = 100 # Starting ID for enemy squads to avoid conflicts

for i in range(NUM_ENEMY_SQUADS):
    enemy_squad_id = ENEMY_START_SQUAD_ID + i
    # Random starting position for the enemy leader
    leader_start_x = random.randint(WIDTH // 4, WIDTH * 3 // 4)
    leader_start_y = random.randint(HEIGHT // 4, HEIGHT * 3 // 4)

    enemy_leader = Boid(leader_start_x, leader_start_y,
                        squad_id=enemy_squad_id, is_leader=True, is_enemy=True)
    enemy_leader.label = f"EL{i+1}"
    # Assign random waypoints for enemy leaders
    enemy_leader.add_waypoint((leader_start_x + random.randint(-150, 150), leader_start_y + random.randint(-150, 150)))
    enemy_leader.add_waypoint((leader_start_x - random.randint(-150, 150), leader_start_y - random.randint(-150, 150)))
    boids.append(enemy_leader)

    for j in range(BOIDS_PER_ENEMY_SQUAD - 1): # -1 because leader is already added
        # Create enemy follower boids
        enemy_follower = Boid(
            leader_start_x + random.randint(-20, 20),
            leader_start_y + random.randint(-20, 20),
            squad_id=enemy_squad_id,
            index=j,
            is_enemy=True
        )
        enemy_follower.label = f"EF{i+1}-{j+1}"
        enemy_follower.leader_ref = enemy_leader # Assign leader
        boids.append(enemy_follower)

# --- Game Loop ---
running = True
clock = pygame.time.Clock()

while running:
    screen.fill((10, 10, 10)) # Dark background

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1: # Left click
                # Check if a player leader was clicked to activate shield
                for b in boids:
                    if b.is_leader and not b.is_enemy and distance(b.position, event.pos) < BOID_RADIUS * 2:
                        b.apply_shield(boids) # Pass all boids for shield application
                        pings.append(Ping(b.position)) # Visual ping for shield activation
            if event.button == 3: # Right click
                # Right-click to set a new waypoint for the closest player leader
                mouse_pos = list(event.pos)
                closest_leader = None
                min_dist = float('inf')
                for b in boids:
                    if b.is_leader and not b.is_enemy:
                        dist = distance(b.position, mouse_pos)
                        if dist < min_dist:
                            min_dist = dist
                            closest_leader = b
                if closest_leader:
                    closest_leader.waypoints = [mouse_pos] # Set new single waypoint
                    closest_leader.current_wp = 0
                    closest_leader.state = 'PATROL' # Ensure leader is in patrol state

    # --- Update and Draw All Game Objects ---

    # Filter out dead boids and inactive projectiles/pings
    boids = [b for b in boids if b.health > 0]
    projectiles = [p for p in projectiles if p.active]
    pings = [p for p in pings if p.active]

    # Update and draw boids
    for b in boids:
        # Pass all boids list to update for flocking, targeting, healing, etc.
        # Pass BOIDS_PER_SQUAD for formation calculation, though this could be more dynamic
        b.update(boids, BOIDS_PER_SQUAD)
        b.draw(screen)

    # Update and draw projectiles
    for p in projectiles:
        p.update()
        p.draw(screen)

    # Update and draw pings
    for ping in pings:
        ping.update()
        ping.draw(screen)

    # Refresh display
    pygame.display.flip()

    # Cap frame rate
    clock.tick(60)

pygame.quit() 