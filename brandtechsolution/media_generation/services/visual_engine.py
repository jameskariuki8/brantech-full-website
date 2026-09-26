"""
Module 8: Visual Intelligence Agent

Automatically generates image prompts, feature illustrations, SVG infographics/diagrams,
social graphics, YouTube thumbnails, image captions, and accessibility alt text for articles.
"""
import logging
from typing import Dict, Any
from editorial.models import EditorialArticle
from editorial.text import fit_to_column
from media_generation.models import MediaAsset

logger = logging.getLogger(__name__)


class VisualIntelligenceAgent:
    """Creates visual media prompts and synthetic SVG diagrams for articles."""

    def generate_visual_package(self, article: EditorialArticle) -> Dict[str, Any]:
        """Generates hero image prompt, alt text, and SVG infographic diagram."""
        logger.info(f"[VisualIntelligenceAgent] Generating visual assets for '{article.title}'...")

        # Construct high-grade Gemini/Midjourney style image prompt
        prompt = (
            f"A futuristic, ultra-high-definition, cinematic 3D visual representing '{article.title}'. "
            f"Style: Sleek cyber-neon, African tech glow, dark glassmorphism, isometric architectural nodes, "
            f"vibrant teal and golden orange highlights on deep obsidian background. 8k resolution."
        )

        # Every string below wraps the title in fixed text, so a title near its
        # own 300-character limit overflows each of these 300-character columns.
        alt_text = fit_to_column(
            MediaAsset, 'alt_text',
            f"Conceptual technical visualization of {article.title} featuring glowing network architecture.",
        )

        article.hero_image_prompt = prompt
        article.image_alt_text = alt_text
        article.save()

        # Create MediaAsset for Hero Image
        hero_asset, _ = MediaAsset.objects.get_or_create(
            article=article,
            asset_type='hero_image',
            defaults={
                'prompt': prompt,
                'alt_text': alt_text,
                'caption': fit_to_column(
                    MediaAsset, 'caption',
                    f"Figure 1: High-level architectural landscape of {article.title}.",
                ),
            }
        )

        # Generate custom SVG infographic block
        svg_code = self._generate_svg_infographic(article.title, article.topic.category if article.topic else "Technology")
        info_asset, _ = MediaAsset.objects.get_or_create(
            article=article,
            asset_type='infographic',
            defaults={
                'prompt': f"Infographic for {article.title}",
                'svg_content': svg_code,
                'alt_text': fit_to_column(
                    MediaAsset, 'alt_text',
                    f"Infographic diagram mapping key layers of {article.title}",
                ),
                'caption': fit_to_column(
                    MediaAsset, 'caption',
                    f"System Architecture & Workflow Diagram: {article.title}",
                ),
            }
        )

        logger.info(f"[VisualIntelligenceAgent] Visual assets generated for '{article.title}'")
        return {
            "hero_asset_id": hero_asset.id,
            "infographic_asset_id": info_asset.id,
            "prompt": prompt,
            "alt_text": alt_text
        }

    def _generate_svg_infographic(self, title: str, category: str) -> str:
        """Generates dynamic high-tech SVG diagram."""
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" width="100%" height="auto">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e293b"/>
    </linearGradient>
    <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#3b82f6"/>
      <stop offset="50%" stop-color="#8b5cf6"/>
      <stop offset="100%" stop-color="#ec4899"/>
    </linearGradient>
  </defs>
  <rect width="800" height="400" rx="16" fill="url(#bgGrad)" stroke="#334155" stroke-width="2"/>
  <text x="40" y="50" fill="#f8fafc" font-family="system-ui, sans-serif" font-size="20" font-weight="700">Teklora Technical Architecture Diagram</text>
  <text x="40" y="80" fill="#94a3b8" font-family="system-ui, sans-serif" font-size="14">{title[:60]}</text>
  
  <!-- Flow Nodes -->
  <rect x="50" y="150" width="200" height="120" rx="12" fill="#1e1e38" stroke="#3b82f6" stroke-width="2"/>
  <text x="70" y="190" fill="#60a5fa" font-family="sans-serif" font-size="14" font-weight="bold">1. Data &amp; Signal Ingestion</text>
  <text x="70" y="220" fill="#cbd5e1" font-family="sans-serif" font-size="12">Multi-source feeds &amp; APIs</text>

  <path d="M 250 210 L 300 210" stroke="url(#accentGrad)" stroke-width="4" marker-end="url(#arrow)"/>

  <rect x="300" y="150" width="200" height="120" rx="12" fill="#1e1e38" stroke="#8b5cf6" stroke-width="2"/>
  <text x="320" y="190" fill="#c084fc" font-family="sans-serif" font-size="14" font-weight="bold">2. Intelligence Processing</text>
  <text x="320" y="220" fill="#cbd5e1" font-family="sans-serif" font-size="12">Gemini 2.5 &amp; Fact Verification</text>

  <path d="M 500 210 L 550 210" stroke="url(#accentGrad)" stroke-width="4"/>

  <rect x="550" y="150" width="200" height="120" rx="12" fill="#1e1e38" stroke="#ec4899" stroke-width="2"/>
  <text x="570" y="190" fill="#f472b6" font-family="sans-serif" font-size="14" font-weight="bold">3. Multi-Channel Output</text>
  <text x="570" y="220" fill="#cbd5e1" font-family="sans-serif" font-size="12">Blog, LinkedIn, RSS &amp; Social</text>
  
  <rect x="40" y="320" width="720" height="4" fill="url(#accentGrad)" rx="2"/>
</svg>'''
