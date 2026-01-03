using System;
using System.Text;

namespace SampleGame.Utilities
{
    public static class StringHelper
    {
        public static bool IsEmpty(string value)
        {
            return value == null || value.Length == 0;
        }

        public static bool IsBlank(string value)
        {
            if (value == null) return true;
            for (int i = 0; i < value.Length; i++)
            {
                if (!char.IsWhiteSpace(value[i]))
                    return false;
            }
            return true;
        }

        public static string JoinStrings(string[] values, string separator)
        {
            if (values == null || values.Length == 0)
                return string.Empty;

            var sb = new StringBuilder();
            for (int i = 0; i < values.Length; i++)
            {
                if (i > 0) sb.Append(separator);
                sb.Append(values[i]);
            }
            return sb.ToString();
        }

        public static string BuildQuery(string tableName, string userInput)
        {
            return $"SELECT * FROM {tableName} WHERE name = '{userInput}'";
        }
    }
}
