# TheEntireWorld
Downloadable Tools for DCC and Content Creation Pipelines; Starting with Animation and Cinematic Exporter for Maya with imports into Unreal 5.5

Instructions for first time using:

1. inside of tools, there will be a .bat file for the version of Maya you use (2023 - 2025 officially tests). It is recommended to run the first time as this will make sure you have the requests module... you may also opt to run maya_setup.py directly
   
2. After that point you should be able to open maya vanilla without the bat file, and the tool should open up and prompt you to select a Uproject

3. You *Must* have an unreal project set up currently for the exports to be added and exported as the tool relies on valid skeleton assets for the rigs you want to export, and it has been developed for 5.5 (future updates will support more versions)

4. Inside Unreal, there is one part that is needed if you want to have the sequence importer work with the Engine open
  
5. Edit > Project Settings > Python > Startup Scripts > Add an Array Element > set the path for the new index to be whatever your local path of  //tools/unreal_tools/http_server.py is... on my PC this is C:/depot/tools/unreal_tools/http_server.py
   
6. I walk through the functionality and how to get this setup in a few vimeo videos, though some updates have happened since then to the UI and the setup... this part is defined there : https://vimeo.com/user58067839 ; https://vimeo.com/user58067839

7. Beyond that once you have the UI open, the videos above show how to use the interface and I will be adding a paper documentation shortly

#To Launch tool

from maya_tools.Cinematics.SequenceUI import sequence_ui

sequence_ui.show_animation_manager()

