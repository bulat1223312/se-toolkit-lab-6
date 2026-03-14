import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import sys
import os

# Добавляем путь к корневой директории проекта, чтобы импортировать agent
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent import read_file, list_files, query_api


class TestReadFile(unittest.TestCase):
    @patch("builtins.open", new_callable=mock_open, read_data="file content")
    def test_read_file_success(self, mock_file):
        rel_path = "test.txt"
        # Ожидаемый абсолютный путь (согласно safe_join)
        expected_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel_path))
        content = read_file(rel_path)
        self.assertEqual(content, "file content")
        mock_file.assert_called_once_with(expected_path, 'r', encoding='utf-8')

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_read_file_not_found(self, mock_file):
        content = read_file("nonexistent.txt")
        self.assertTrue(content.startswith("Error reading file:"))


class TestListFiles(unittest.TestCase):
    @patch("os.listdir", return_value=["file1.txt", "file2.txt"])
    def test_list_files_success(self, mock_listdir):
        result = list_files("somedir")
        self.assertEqual(result, "file1.txt\nfile2.txt")

    @patch("os.listdir", side_effect=FileNotFoundError)
    def test_list_files_not_found(self, mock_listdir):
        result = list_files("nonexistent")
        self.assertTrue(result.startswith("Error listing directory:"))


class TestQueryAPI(unittest.TestCase):
    @patch("agent.requests.request")
    def test_query_api_get_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"items": [1,2,3]}'
        mock_request.return_value = mock_response

        # Подменяем переменные окружения на время теста
        with patch.dict(os.environ, {"LMS_API_KEY": "test-key", "AGENT_API_BASE_URL": "http://test:8000"}):
            result = query_api("GET", "/items/")
            data = json.loads(result)
            self.assertEqual(data["status_code"], 200)
            self.assertEqual(data["body"], '{"items": [1,2,3]}')

            # Проверяем, что request был вызван один раз
            mock_request.assert_called_once()
            args, kwargs = mock_request.call_args
            self.assertEqual(kwargs['method'], "GET")
            self.assertEqual(kwargs['url'], "http://test:8000/items/")
            self.assertEqual(kwargs['headers']["Authorization"], "Bearer test-key")
            self.assertIsNone(kwargs['json'])
            self.assertEqual(kwargs['timeout'], 10)

    @patch("agent.requests.request")
    def test_query_api_post_with_body(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"id": 1}'
        mock_request.return_value = mock_response

        with patch.dict(os.environ, {"LMS_API_KEY": "test-key", "AGENT_API_BASE_URL": "http://test:8000"}):
            result = query_api("POST", "/items/", body='{"name": "test"}')
            data = json.loads(result)
            self.assertEqual(data["status_code"], 201)
            self.assertEqual(data["body"], '{"id": 1}')

            mock_request.assert_called_once()
            args, kwargs = mock_request.call_args
            self.assertEqual(kwargs['method'], "POST")
            self.assertEqual(kwargs['url'], "http://test:8000/items/")
            self.assertEqual(kwargs['headers']["Authorization"], "Bearer test-key")
            self.assertEqual(kwargs['json'], {"name": "test"})
            self.assertEqual(kwargs['timeout'], 10)

    def test_query_api_missing_key(self):
        # Полностью очищаем окружение, чтобы ключа не было
        with patch.dict(os.environ, {}, clear=True):
            result = query_api("GET", "/items/")
            data = json.loads(result)
            self.assertEqual(data["status_code"], 500)
            self.assertEqual(data["body"], "LMS_API_KEY not set")

    @patch("agent.requests.request", side_effect=Exception("Connection error"))
    def test_query_api_request_exception(self, mock_request):
        with patch.dict(os.environ, {"LMS_API_KEY": "test-key"}):
            result = query_api("GET", "/items/")
            data = json.loads(result)
            self.assertEqual(data["status_code"], 500)
            self.assertIn("Connection error", data["body"])


if __name__ == "__main__":
    unittest.main()