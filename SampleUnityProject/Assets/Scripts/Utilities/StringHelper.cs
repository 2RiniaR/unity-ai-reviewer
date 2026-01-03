namespace SampleGame.Utilities
{
    public static class StringHelper
    {
        public static bool IsEmpty(string value)
        {
            return value == null || value.Length == 0;
        }
    }
}
