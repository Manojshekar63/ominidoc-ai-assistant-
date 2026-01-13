# OmniDoc Assistant

OmniDoc Assistant is a universal document intelligence assistant that allows users to interact with various document formats, including PDF and DOCX. The application leverages advanced language models to provide insights and answers based on the content of the uploaded documents or fetched URLs.

## Features

- Upload PDF or DOCX files for processing.
- Fetch content from public Google Drive and Google Docs links.
- Voice input support for querying the assistant.
- Text-to-speech functionality to hear answers.
- Search history management to reuse previous queries.

## Requirements

To run the OmniDoc Assistant, you need to install the required dependencies listed in the `requirements.txt` file.

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd omnidoc-assistant
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Running the Application

To start the application, run the following command:
```
streamlit run app.py
```

## Usage

- Upload a PDF or DOCX document or enter a public URL to fetch content.
- Ask questions using text input or voice commands.
- Review the answers provided by the assistant, along with the sources used for generating the responses.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.