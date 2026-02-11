
import unittest
import os
import json
from src.core.calibration import CalibrationManager

class TestProfileIndependence(unittest.TestCase):
    def setUp(self):
        self.config_path = "test_sync.json"
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
            
        self.cm = CalibrationManager(self.config_path)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def test_profile_independence(self):
        # 1. Create Profile A
        print("\nCreating Profile A with sensitivity 2.0")
        self.cm.set_input_sensitivity(2.0)
        self.cm.save_profile("Profile A", "Device A")
        self.cm.set_last_profile("Profile A")
        
        # 2. Create Profile B (Save As)
        print("Creating Profile B (copy of A)")
        self.cm.save_profile("Profile B", "Device B")
        # Switch to B
        self.cm.load_profile("Profile B")
        self.assertEqual(self.cm.last_profile, "Profile B")
        
        # 3. Modify Profile B
        print("Modifying Profile B to sensitivity 5.0")
        self.cm.set_input_sensitivity(5.0)
        
        # Check in memory
        self.assertEqual(self.cm.profiles["Profile B"]["input_sensitivity"], 5.0)
        self.assertEqual(self.cm.profiles["Profile A"]["input_sensitivity"], 2.0, "Profile A should remain 2.0 while editing B")
        
        # Check on disk
        with open(self.config_path, "r") as f:
            data = json.load(f)
            prof_a = data["profiles"]["Profile A"]["input_sensitivity"]
            prof_b = data["profiles"]["Profile B"]["input_sensitivity"]
            print(f"Disk - Profile A: {prof_a}, Profile B: {prof_b}")
            
            self.assertEqual(prof_b, 5.0)
            self.assertEqual(prof_a, 2.0, "Profile A on disk should remain 2.0")

        # 4. Switch back to A
        print("Switching back to Profile A")
        self.cm.load_profile("Profile A")
        self.assertEqual(self.cm.input_sensitivity, 2.0)
        
        # 5. Modify Profile A
        print("Modifying Profile A to sensitivity 3.0")
        self.cm.set_input_sensitivity(3.0)
        
        # Check B
        b_val = self.cm.profiles["Profile B"]["input_sensitivity"]
        print(f"Profile B value after modifying A: {b_val}")
        self.assertEqual(b_val, 5.0, "Profile B should remain 5.0 while editing A")

if __name__ == "__main__":
    unittest.main()
