import logging
import os
import asyncio
import google.generativeai as genai
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


async def setup_gemini():
    """Setup Gemini API client"""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.error("GEMINI_API_KEY environment variable is not set")
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    
    logger.info(f"Configuring Gemini with API key (length: {len(api_key)})")
    genai.configure(api_key=api_key)
    
    try:
        # Try to list available models first
        logger.info("Listing available models...")
        try:
            available_models = genai.list_models()
            model_names = [m.name for m in available_models]
            logger.info(f"Available models: {model_names}")
        except Exception as e:
            logger.warning(f"Could not list available models: {str(e)}")
            model_names = []
        
        # Preferred model types in order
        preferred_types = [
            'gemini-2.0-flash',
            'gemini-1.5-flash',
            'gemini-1.5-pro',
            'gemini-pro'
        ]
        
        # If we have model names from the API, use those and prioritize by preference
        possible_models = []
        if model_names:
            # Add exact models from API response, prioritized by preference
            for preferred in preferred_types:
                matching_models = [name for name in model_names if preferred in name]
                possible_models.extend(matching_models)
            
            # Add any remaining models that weren't matched
            remaining_models = [name for name in model_names if name not in possible_models and 'gemini' in name]
            possible_models.extend(remaining_models)
        
        # Add fallback models if we couldn't get the list or nothing else worked
        if not possible_models:
            possible_models = [
                'models/gemini-2.0-flash',
                'models/gemini-1.5-flash', 
                'models/gemini-1.5-pro',
                'gemini-pro'
            ]
        
        logger.info(f"Models to try in order: {possible_models}")
        
        # Try each model until one works
        last_error = None
        for model_name in possible_models:
            try:
                # Strip 'models/' prefix if present when creating the model
                model_id = model_name.replace('models/', '') if model_name.startswith('models/') else model_name
                logger.info(f"Trying model {model_name} with ID: {model_id}")
                model = genai.GenerativeModel(model_id)
                logger.info(f"Successfully initialized Gemini model: {model_name}")
                return model
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to initialize model {model_name}: {str(e)}")
                continue
        
        # If we get here, no models worked
        if last_error:
            raise last_error
        else:
            raise ValueError("No Gemini models could be initialized")
    except Exception as e:
        logger.error(f"Error initializing Gemini model: {type(e).__name__}: {str(e)}")
        raise


async def generate_educational_content(topic: str, previous_contents: Optional[List[str]] = None, 
                              is_preview: bool = False, difficulty: str = "medium"):
    """
    Generate educational content about a topic
    
    Args:
        topic: The topic to generate content about
        previous_contents: Optional list of previous email contents
        is_preview: Whether this is a preview (shorter content)
        difficulty: Content difficulty level (easy, medium, hard)
        
    Returns:
        HTML formatted educational content or None on error
    """
    try:
        # Validate and sanitize topic
        if not topic or not isinstance(topic, str):
            logger.error("Invalid topic provided to content generator")
            return None
            
        # Basic input sanitization
        sanitized_topic = ''.join(c for c in topic if c.isalnum() or c.isspace() or c in '-_.,')
        
        if not sanitized_topic:
            logger.error("Topic contains only invalid characters")
            return None
            
        # Setup Gemini
        model = await setup_gemini()
        
        # Process previous content if available
        history_context = ""
        if previous_contents and not is_preview:
            if isinstance(previous_contents, list) and all(isinstance(item, str) for item in previous_contents):
                history_context = "Previous lessons covered:\n" + "\n".join(previous_contents[-3:])  # Last 3 emails
            else:
                logger.warning("Invalid previous_contents format provided")
                history_context = ""

        # Adjust content length based on preview mode
        length_instruction = "concise and brief" if is_preview else "concise but informative"
        
        # Adjust difficulty level
        difficulty_instruction = ""
        if difficulty == "easy":
            difficulty_instruction = "Use simple language and basic concepts. Explain as if to a beginner."
        elif difficulty == "hard":
            difficulty_instruction = "Use advanced concepts and terminology appropriate for someone familiar with the subject."
        else:  # medium
            difficulty_instruction = "Use moderately technical language appropriate for an interested learner."
        
        # Create appropriate prompt based on mode
        if is_preview:
            prompt = f"""Create a SHORT educational content preview about {sanitized_topic}. 
This is a PREVIEW to show users what kind of content they will receive.
{difficulty_instruction}
Structure the response exactly as follows:

1. Start with "**Subject: [Topic-specific engaging title]**"
2. Begin with a brief interesting fact starting with "Did you know..."
3. Follow with a very concise explanation titled "Here's why this matters:"
4. End with a brief thought-provoking question titled "Question for Reflection:"

Keep the language friendly and engaging. This is a PREVIEW so keep it brief (about 30-40% the length of a full lesson)."""
        else:
            prompt = f"""Create an educational email about {sanitized_topic}. 
{history_context}
{difficulty_instruction}
Please create new content that builds upon previous lessons if available.
Structure the response exactly as follows:

1. Start with "**Subject: [Topic-specific engaging title]**"
2. Begin with an interesting fact starting with "Did you know..."
3. Follow with a clear explanation titled "Here's why this matters:"
4. Include a practical example or application titled "Let's see it in action:"
5. End with a thought-provoking question titled "Question for Reflection:"

Keep the language friendly and engaging, and ensure each section is {length_instruction}."""

        # Generate content
        logger.debug(f"Sending prompt to Gemini API for sanitized topic: {sanitized_topic}")
        response = await asyncio.to_thread(model.generate_content, prompt)
        content = response.text
        logger.debug("Successfully received response from Gemini API")

        # Format the content with HTML
        # First remove any remaining ** marks
        content = content.replace("**", "")
        
        # Create different formatting for preview vs full content
        if is_preview:
            # Preview formatting (simpler, more compact)
            formatted_content = content.replace(
                "Subject:", "<h2 style='color: #2c3e50; margin-bottom: 15px;'>").replace(
                "\n", "</h2>", 1).replace(
                "Did you know", "<p><strong>Did you know</strong>").replace(
                "Here's why this matters:", "</p><h3 style='color: #34495e; margin-top: 15px;'>Why This Matters:</h3><p>").replace(
                "Question for Reflection:", "</p><h3 style='color: #34495e; margin-top: 15px;'>Think About This:</h3><p>")
            
            # Add preview badge
            formatted_content = f"<div class='preview-badge' style='background: #f0f8ff; border: 1px solid #b3d7ff; color: #0056b3; padding: 5px 10px; display: inline-block; margin-bottom: 15px; border-radius: 4px; font-size: 0.8rem;'>Content Preview ({difficulty} level)</div>" + formatted_content
        else:
            # Full content formatting
            formatted_content = content.replace(
                "Subject:", "<h2 style='color: #2c3e50; margin-bottom: 20px;'>").replace(
                "\n", "</h2>", 1).replace(
                "Did you know", "<p><strong>Did you know</strong>").replace(
                "Here's why this matters:", "</p><h3 style='color: #34495e; margin-top: 20px;'>Understanding the Concept:</h3><p>").replace(
                "Let's see it in action:", "</p><h3 style='color: #34495e; margin-top: 20px;'>Practical Application:</h3><p>").replace(
                "Question for Reflection:", "</p><h3 style='color: #34495e; margin-top: 20px;'>Think About This:</h3><p>")

        # Ensure the content ends with a closing paragraph tag
        if not formatted_content.endswith("</p>"):
            formatted_content += "</p>"
            
        # Add a disclaimer for preview content
        if is_preview:
            formatted_content += "<div style='border-top: 1px solid #eee; margin-top: 20px; padding-top: 10px; font-style: italic; font-size: 0.9rem; color: #777;'>This is a preview of the type of content you'll receive. Actual lessons will be more detailed and include practical examples.</div>"

        return formatted_content
    except Exception as e:
        logger.error(f"Error generating content: {type(e).__name__}: {str(e)}")
        return None