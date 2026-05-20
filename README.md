# AI Interview Simulation and Training System

Chinese title: AI面试问答模拟与培训系统

This project is a full-stack AI-assisted interview training platform designed for job seekers. It simulates an online interview workflow, collects text, speech, and camera-based signals during the session, and generates structured scoring reports with improvement suggestions.

The project was built as an applied AI and web engineering practice project. It focuses on connecting real user workflows with AI capabilities, rather than only providing a static question bank.

## Key Features

- User registration, login, profile management, and local login-state handling.
- Job-category selection for multiple technical roles, including frontend, backend, testing, algorithms, AI engineering, data engineering, DevOps, cybersecurity, and architecture.
- Interview question bank with reference answers and keyword metadata.
- Simulated interview workflow with timed questions, answer collection, speech recording, and camera-based status sampling.
- Speech-to-text integration for converting spoken answers into text.
- Text-answer analysis based on answer length, keyword coverage, structure, and logic indicators.
- Face detection and non-verbal behavior analysis with an OpenCV fallback.
- Multi-dimensional scoring report covering content quality, verbal expression, and non-verbal performance.
- Interview history and review pages for post-interview reflection.

## Tech Stack

| Layer | Technologies |
| --- | --- |
| Backend | Python, Flask, Flask-CORS |
| Database | MySQL, PyMySQL |
| Frontend | HTML5, CSS3, JavaScript |
| Security | bcrypt password hashing |
| AI / Media | Speech recognition API, LLM API, OpenCV Haar Cascade |
| Browser APIs | getUserMedia, AudioContext, SpeechRecognition, FaceDetector |

## System Design

The system follows a frontend-backend separation pattern.

```text
frontend/
  index.html             Login and registration page
  home.html              Home dashboard
  job_selection.html     Job category selection
  interview.html         Main simulated interview page
  result.html            Interview result page
  question_bank.html     Question bank browser
  history.html           Interview history
  profile.html           User profile

backend/
  app.py                 Flask application, REST APIs, database logic
  xf_api.py              AI API client and multimodal scoring engine
  requirements.txt       Python dependencies
  questions_clean.json   Cleaned question-bank data
  comprehensive_questions.json
  import_*.py            Question import scripts
  *_crawler.py           Question crawling scripts
```

## Multimodal Scoring Model

The scoring engine evaluates interview performance from three dimensions:

| Dimension | Weight | Signals |
| --- | ---: | --- |
| Non-verbal performance | 40% | face presence, face coverage, frontal posture, attention, expression stability |
| Verbal expression | 25% | fluency, clarity, hesitation markers, repeated words, sentence structure |
| Answer content | 35% | professional relevance, keyword coverage, logical depth, completeness |

The system also includes penalties for empty, extremely short, or invalid answers. This prevents a user from receiving an unrealistically high score when the camera status is acceptable but the actual answer content is weak.

## Implementation Highlights

- Built RESTful APIs for user management, question retrieval, interview initialization, speech recognition, face detection, scoring, history lookup, and favorites.
- Designed MySQL tables for users, questions, interview records, user preferences, and favorites.
- Used JSON fields to store interview questions, answers, and detailed score reports for flexible history review.
- Implemented browser-side audio collection and conversion before submitting audio data to the backend.
- Added OpenCV-based local face detection as a fallback when external AI services are unavailable.
- Refactored sensitive credentials into environment variables before publishing the project.

## Database Schema

The backend expects a MySQL database named `ai_interview_system`.

Main tables:

- `users`: user accounts, hashed passwords, email, and creation time.
- `questions`: job category, question text, reference answer, and keywords.
- `interview_records`: user ID, job category, questions, answers, detailed scores, and total score.
- `user_preferences`: preferred categories, interview duration, and notification settings.
- `favorites`: saved questions for each user.

## API Overview

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/register` | POST | Register a user |
| `/api/login` | POST | User login |
| `/api/job_categories` | GET | Get job categories |
| `/api/questions` | POST | Get interview questions |
| `/api/interview/init` | POST | Initialize an interview |
| `/api/interview/face_detect` | POST | Detect face and expression status |
| `/api/interview/asr` | POST | Convert speech audio to text |
| `/api/interview/analyze_text` | POST | Analyze answer text |
| `/api/interview/multimodal_score` | POST | Generate multimodal score report |
| `/api/history/<user_id>` | GET | Get interview history |
| `/api/history/detail/<record_id>` | GET | Get detailed interview record |
| `/api/user/<user_id>/favorites` | GET / POST | Query or add favorite questions |

## Local Setup

1. Create the MySQL database.

```sql
CREATE DATABASE ai_interview_system
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

2. Create a local environment file.

Copy `.env.example` to `.env` and fill in your own local configuration:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=ai_interview_system

DOUBAO_API_KEY=
DOUBAO_API_URL=https://ark.cn-beijing.volces.com/api/v3/chat/completions

XF_APP_ID=
XF_API_KEY=
XF_API_SECRET=
```

3. Install backend dependencies.

```bash
cd backend
pip install -r requirements.txt
```

4. Start the backend service.

```bash
python app.py
```

The default service address is:

```text
http://127.0.0.1:5000
```

5. Open the frontend.

```text
http://127.0.0.1:5000
```

## Application Flow

1. Register or log in.
2. Select a target job category.
3. Start a simulated interview.
4. Grant camera and microphone permissions.
5. Answer each question by voice or text.
6. Submit the interview.
7. View the AI-generated scoring report.
8. Review previous interview records in the history page.

## Project Value

This project demonstrates:

- full-stack web application development;
- database-backed business workflow design;
- integration of speech recognition and LLM-style AI APIs;
- multimodal evaluation logic for a practical education/training scenario;
- engineering awareness around fallback design, structured scoring, and safe public release.

## Future Improvements

- Replace localStorage-only login state with JWT or server-side sessions.
- Add an administrator dashboard for managing question-bank data.
- Improve semantic scoring with stronger language models.
- Add charts for long-term progress tracking across multiple interview sessions.
- Migrate the frontend to a component-based framework such as Vue or React.

## Repository Notes

Sensitive credentials are intentionally not committed. Use `.env.example` as the configuration template.

Local virtual environments, IDE settings, Python caches, and database dump files are excluded through `.gitignore`.
